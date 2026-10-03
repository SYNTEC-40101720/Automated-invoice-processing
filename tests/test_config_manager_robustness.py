"""配置管理健壮性测试：% 插值 / GBK / BOM / 密文损坏 / 非法端口。

load_config 走真实磁盘文件（tmp_path），隔离 _get_program_dir 指向。
"""
import os

import pytest
from invoice_processor import config_manager
from invoice_processor.config_manager import load_config, set_all_config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """把 config.ini 定位到 tmp_path，并清空已缓存的 ConfigManager store"""
    config_path = tmp_path / 'config.ini'
    monkeypatch.setattr(
        config_manager, 'get_config_path', lambda: str(config_path)
    )
    monkeypatch.setattr(
        config_manager, '_get_program_dir', lambda: str(tmp_path)
    )
    monkeypatch.setattr(config_manager, '_CONFIG_STORES', {})
    yield tmp_path
    config_manager._CONFIG_STORES.clear()


class TestPercentValues:
    def test_set_and_read_percent_value(self, isolated_config):
        """关键词含 % 可正常写入并读回（interpolation=None）"""
        set_all_config(email={'keywords': '报销100%'})
        assert config_manager.get_email_keywords() == ['报销100%']

    def test_read_percent_from_hand_edited_file(self, isolated_config):
        """手编 config.ini 里的 % 值不再让 get 崩溃"""
        path = isolated_config / 'config.ini'
        path.write_text(
            '[email]\nkeywords = 报销100%\n', encoding='utf-8'
        )
        assert config_manager.get_email_keywords() == ['报销100%']


class TestEncodingRobustness:
    def test_gbk_file_falls_back_to_defaults(self, isolated_config):
        """GBK/ANSI 编码的 config.ini 不再 import 期崩溃，回退默认配置"""
        path = isolated_config / 'config.ini'
        path.write_bytes(
            '[business]\ntarget_tax_id = 中文税号\n'.encode('gbk')
        )
        cfg = load_config()
        # 读入失败 → 默认值兜底，应用可启动
        assert cfg.get(
            'business', 'target_tax_id',
            fallback=config_manager._DEFAULTS['business']['target_tax_id'],
        ) == config_manager._DEFAULTS['business']['target_tax_id']

    def test_bom_file_values_survive(self, isolated_config):
        """带 BOM 的 config.ini 首段不再被丢弃，值能读回（防默认值覆写链）"""
        path = isolated_config / 'config.ini'
        path.write_bytes(
            b'\xef\xbb\xbf[business]\ntarget_tax_id = TAX-KEEP\n'
            b'max_workers = 6\n'
        )
        cfg = load_config()
        assert cfg.get('business', 'target_tax_id', fallback='') == 'TAX-KEEP'
        assert cfg.get('business', 'max_workers', fallback='') == '6'

    def test_bom_file_patch_preserves_other_values(self, isolated_config):
        """BOM 文件上保存单段配置不丢其余段值（覆写链回归测试）"""
        path = isolated_config / 'config.ini'
        path.write_bytes(
            b'\xef\xbb\xbf[business]\ntarget_tax_id = TAX-KEEP\n'
            b'max_workers = 6\n[email]\nusername = me@test\n'
        )
        set_all_config(ai={'model': 'other-model'})
        # 重读文件：business/email 段原值保留
        content = path.read_text(encoding='utf-8-sig')
        assert 'TAX-KEEP' in content
        assert 'me@test' in content
        assert 'other-model' in content
        # 写出的文件无 BOM（devbase 写路径固定 utf-8 无 BOM）
        assert not path.read_bytes().startswith(b'\xef\xbb\xbf')


class TestSecretDecryptRobustness:
    def test_corrupted_dpapi_ciphertext_returns_empty(self, isolated_config,
                                                      monkeypatch):
        """损坏密文解密失败 → 按未配置处理，不抛异常"""
        from devbase.secret_store import SecretStoreError

        def broken_unprotect(self, value):
            raise SecretStoreError('invalid protected secret encoding')

        monkeypatch.setattr(
            'invoice_processor.secret_store.SecretStore.unprotect',
            broken_unprotect,
        )
        assert config_manager.get_email_auth_code() == ''
        assert config_manager.get_ai_api_key() == ''

    def test_cross_machine_dpapi_ciphertext_returns_empty(self, isolated_config,
                                                          monkeypatch):
        """跨机器迁移的密文（unprotect 抛 OSError）→ 按未配置处理"""
        def broken_unprotect(self, value):
            raise OSError('CryptUnprotectData failed')

        monkeypatch.setattr(
            'invoice_processor.secret_store.SecretStore.unprotect',
            broken_unprotect,
        )
        assert config_manager.get_email_auth_code() == ''


class TestSingleKeyRobustness:
    def test_imap_port_invalid_falls_back_in_settings(self, monkeypatch):
        """手编非法 imap_port → settings 渲染回退 993，不再 500"""
        from invoice_processor.api.routes import settings as settings_route

        monkeypatch.setattr(
            settings_route, 'get_email_config', lambda: {
                'imap_host': 'imap.qq.com', 'imap_port': 'abc',
                'username': 'u', 'auth_code': '',
                'inbox_dir': 'inbox', 'days_back': '30',
                'senders': '', 'keywords': '',
            }
        )
        monkeypatch.setattr(
            settings_route, 'get_email_username', lambda: 'u'
        )
        monkeypatch.setattr(
            settings_route, 'get_email_days_back', lambda: 30
        )
        monkeypatch.setattr(
            settings_route, 'get_email_senders', lambda: []
        )
        monkeypatch.setattr(
            settings_route, 'get_email_keywords', lambda: []
        )
        monkeypatch.setattr(
            settings_route, 'get_inbox_dir', lambda: 'C:/inbox'
        )
        monkeypatch.setattr(
            settings_route, 'get_email_auth_code', lambda: ''
        )
        monkeypatch.setattr(
            settings_route, 'get_target_tax_id', lambda: 'TAX'
        )
        monkeypatch.setattr(
            settings_route, 'get_max_workers', lambda: 8
        )
        monkeypatch.setattr(
            settings_route, 'get_ai_enabled', lambda: False
        )
        monkeypatch.setattr(
            settings_route, 'get_ai_api_base', lambda: 'https://api.test'
        )
        monkeypatch.setattr(
            settings_route, 'get_ai_model', lambda: 'm'
        )
        monkeypatch.setattr(
            settings_route, 'get_ai_timeout', lambda: 60
        )
        monkeypatch.setattr(
            settings_route, 'get_ai_api_key', lambda: ''
        )
        response = settings_route._settings()
        assert response.email.imap_port == 993


class TestAutoProcessParsing:
    def test_auto_process_default_false(self, isolated_config):
        """未配置 auto_process 时默认关闭"""
        assert config_manager.get_email_auto_process() is False

    def test_auto_process_true_values(self, isolated_config):
        """'true'/'1'/'yes'/'on'（大小写不敏感）解析为开启"""
        for raw in ('true', 'True', '1', 'yes', 'ON'):
            set_all_config(email={'auto_process': raw})
            assert config_manager.get_email_auto_process() is True, raw

    def test_auto_process_invalid_falls_back_false(self, isolated_config):
        """手编非法值回退关闭，不抛异常"""
        set_all_config(email={'auto_process': '随便写的'})
        assert config_manager.get_email_auto_process() is False


class TestInboxDirExpansion:
    def test_inbox_dir_expands_user_home(self, isolated_config, monkeypatch):
        """~ 开头的收件目录与 job_service 的 expanduser 口径一致"""
        fake_home = isolated_config / 'home'
        fake_home.mkdir()
        monkeypatch.setenv('USERPROFILE', str(fake_home))
        monkeypatch.setenv('HOME', str(fake_home))
        set_all_config(email={'inbox_dir': '~/收件箱'})
        assert os.path.realpath(config_manager.get_inbox_dir()) == os.path.realpath(
            str(fake_home / '收件箱')
        )

"""原生桥路径边界测试。"""

from invoice_processor.desktop.native_bridge import NativeBridge


def test_open_directory_requires_backend_approval(tmp_path):
    bridge = NativeBridge(lambda _: False)

    assert bridge.open_directory(str(tmp_path)) is False


def test_write_log_only_uses_path_selected_by_save_dialog(tmp_path, monkeypatch):
    target = tmp_path / 'export.txt'

    class FakeRoot:
        def destroy(self):
            pass

    monkeypatch.setattr(
        NativeBridge,
        '_dialog_root',
        staticmethod(lambda: FakeRoot()),
    )
    monkeypatch.setattr(
        'invoice_processor.desktop.native_bridge.filedialog.asksaveasfilename',
        lambda **_: str(target),
    )
    bridge = NativeBridge()

    assert bridge.write_log('before selection') is False
    assert bridge.save_log_dialog() == str(target)
    assert bridge.write_log('exported') is True
    assert target.read_text(encoding='utf-8') == 'exported'
    assert bridge.write_log('second write') is False

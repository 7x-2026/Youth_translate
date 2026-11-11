import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from dotenv import dotenv_values

import desktop_launcher
from backend import runtime, system_audio, windows_audio
from backend.config import Settings


def test_changing_key_preserves_other_configuration_and_updates_running_settings(tmp_path):
    path = tmp_path / 'config.env'
    path.write_text("PORT=9876\nVOLC_RESOURCE_ID='custom-resource'\n")
    original = Settings(api_key='previous-test-key', port=9876, resource_id='custom-resource')
    updated = desktop_launcher.update_api_key(original, ' replacement-test-key ', path)
    assert updated.api_key == 'replacement-test-key'
    assert updated.response_mode == 'delta'
    assert updated.port == original.port and updated.resource_id == original.resource_id
    assert original.api_key == 'previous-test-key'
    assert dotenv_values(path) == dict(PORT='9876', VOLC_RESOURCE_ID='custom-resource',
        VOLC_API_KEY='replacement-test-key', VOLC_SUBTITLE_RESPONSE_MODE='delta')


def test_failed_key_save_keeps_previous_configuration_intact(tmp_path, monkeypatch):
    import dotenv

    path = tmp_path / 'config.env'
    desktop_launcher.save_configuration('previous-test-key', path)
    previous = path.read_bytes()
    original_set = dotenv.set_key
    def fail_second_field(filename, field, value, **options):
        if field == 'VOLC_SUBTITLE_RESPONSE_MODE':
            raise OSError('test disk write failure')
        return original_set(filename, field, value, **options)
    monkeypatch.setattr(dotenv, 'set_key', fail_second_field)
    with pytest.raises(OSError):
        desktop_launcher.save_configuration('replacement-test-key', path)
    assert path.read_bytes() == previous


def test_frozen_configuration_is_outside_bundle_and_survives_move(tmp_path, monkeypatch):
    local = tmp_path / 'user data'
    monkeypatch.setenv('LOCALAPPDATA', str(local))
    monkeypatch.setattr(runtime, 'sys', SimpleNamespace(platform='win32', frozen=True))
    first = runtime.configuration_path()
    database = runtime.records_path()
    desktop_launcher.save_configuration("test-key-with-'quote", first)
    monkeypatch.setattr(runtime, 'ROOT', tmp_path / 'different-exe-extraction')
    assert runtime.configuration_path() == first
    assert runtime.records_path() == database == local / 'ClassroomInterpreter/records.sqlite3'
    config = dotenv_values(first)
    assert config['VOLC_API_KEY'] == "test-key-with-'quote"
    assert config['VOLC_SUBTITLE_RESPONSE_MODE'] == 'delta'
    assert first.parent == local / 'ClassroomInterpreter'


@pytest.mark.parametrize('key', ['', 'ark-not-a-voice-key', 'key\ninjection', 'key\rline', 'key\0null'])
def test_invalid_configuration_cannot_replace_saved_key(tmp_path, key):
    path = tmp_path / 'config.env'
    desktop_launcher.save_configuration('previous-test-key', path)
    with pytest.raises(ValueError):
        desktop_launcher.save_configuration(key, path)
    assert dotenv_values(path)['VOLC_API_KEY'] == 'previous-test-key'


def test_source_configuration_keeps_existing_project_env(monkeypatch):
    monkeypatch.setattr(runtime, 'sys', SimpleNamespace(platform='darwin'))
    assert runtime.configuration_path() == runtime.ROOT / '.env'


def test_macos_configuration_and_records_survive_application_replacement(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(runtime, 'sys', SimpleNamespace(platform='darwin', frozen=True))
    directory = tmp_path / 'Library/Application Support/ClassroomInterpreter'
    desktop_launcher.save_configuration('test-macos-key', runtime.configuration_path())
    monkeypatch.setattr(runtime, 'ROOT', tmp_path / 'replacement.app/Contents/Resources')
    assert runtime.configuration_path() == directory / 'config.env'
    assert runtime.records_path() == directory / 'records.sqlite3'
    assert dotenv_values(runtime.configuration_path())['VOLC_API_KEY'] == 'test-macos-key'


async def test_frozen_macos_uses_relocated_helper_without_source_or_compiler(tmp_path, monkeypatch):
    executable = tmp_path / '青衿 Classroom.app/Contents/MacOS/ClassroomInterpreter'
    fake_sys = SimpleNamespace(platform='darwin', frozen=True, executable=str(executable))
    monkeypatch.setattr(runtime, 'sys', fake_sys)
    monkeypatch.setattr(system_audio, 'sys', fake_sys)
    monkeypatch.setattr(system_audio, 'supported', lambda: True)
    helper = runtime.bundled_audio_binary()
    helper.parent.mkdir(parents=True)
    helper.touch()
    spawn = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(system_audio.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setenv('VOLC_API_KEY', 'must-not-reach-helper')
    await system_audio.SystemAudio().spawn(['--list'])
    assert spawn.call_args.args == (str(helper), '--list')
    assert 'VOLC_API_KEY' not in spawn.call_args.kwargs['env']


async def test_missing_packaged_macos_helper_does_not_try_to_build_on_user_machine(tmp_path, monkeypatch):
    fake_sys = SimpleNamespace(platform='darwin', frozen=True,
                               executable=str(tmp_path / 'Incomplete.app/Contents/MacOS/app'))
    monkeypatch.setattr(runtime, 'sys', fake_sys)
    monkeypatch.setattr(system_audio, 'sys', fake_sys)
    monkeypatch.setattr(system_audio, 'supported', lambda: True)
    spawn = AsyncMock()
    monkeypatch.setattr(system_audio.asyncio, 'create_subprocess_exec', spawn)
    with pytest.raises(system_audio.RelayError, match='重新安装'):
        await system_audio.SystemAudio().command()
    spawn.assert_not_awaited()


@pytest.mark.parametrize('arguments,interactive', [(['--list'],False),(['--list-and-wait'],True)])
async def test_frozen_worker_uses_executable_entry_and_hides_console_without_credentials(tmp_path, monkeypatch, arguments, interactive):
    process = SimpleNamespace()
    spawn = AsyncMock(return_value=process)
    executable=str(tmp_path / '课堂 程序' / 'app.exe')
    monkeypatch.setattr(system_audio, 'sys', SimpleNamespace(platform='win32', frozen=True, executable=executable))
    monkeypatch.setattr(system_audio.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setenv('VOLC_API_KEY', 'test-key-must-not-leak')
    monkeypatch.setenv('TENCENT_SECRET_KEY', 'another-key-must-not-leak')
    monkeypatch.setenv('_PYI_ARCHIVE_FILE', str(tmp_path / 'app.exe'))
    monkeypatch.setenv('_PYI_APPLICATION_HOME_DIR', str(tmp_path / '_MEI123'))
    monkeypatch.setenv('_PYI_PARENT_PROCESS_LEVEL', '1')
    monkeypatch.setenv('PYINSTALLER_RESET_ENVIRONMENT', '1')
    capture = system_audio.SystemAudio()
    await capture.spawn(arguments, interactive=interactive)
    assert spawn.call_args.args == (executable, '--audio-worker', *arguments)
    assert spawn.call_args.kwargs['stdin'] == (system_audio.asyncio.subprocess.PIPE if interactive else system_audio.asyncio.subprocess.DEVNULL)
    assert spawn.call_args.kwargs['creationflags'] == 0x08000000
    assert 'VOLC_API_KEY' not in spawn.call_args.kwargs['env']
    assert 'TENCENT_SECRET_KEY' not in spawn.call_args.kwargs['env']
    environment = spawn.call_args.kwargs['env']
    assert environment['_PYI_ARCHIVE_FILE'] == str(tmp_path / 'app.exe')
    assert environment['_PYI_APPLICATION_HOME_DIR'] == str(tmp_path / '_MEI123')
    assert environment['_PYI_PARENT_PROCESS_LEVEL'] == '1'
    assert 'PYINSTALLER_RESET_ENVIRONMENT' not in environment
    assert spawn.call_args.kwargs['stdout'] is not None


@pytest.mark.parametrize('arguments', [['--device','headphones'],['--list-and-wait']])
def test_worker_dispatch_preserves_arguments_and_does_not_launch_gui(monkeypatch,arguments):
    received = []
    monkeypatch.setattr(windows_audio, 'main', lambda argv: received.append(argv) or 2)
    monkeypatch.setattr(desktop_launcher, 'launch', lambda: pytest.fail('audio worker must not open UI'))
    assert desktop_launcher.main(['--audio-worker', *arguments]) == 2
    assert received == [arguments]


def test_windows_worker_list_emits_only_json(monkeypatch, capsys):
    devices = [SimpleNamespace(id='speaker', name='教室耳机')]
    monkeypatch.setitem(sys.modules, 'soundcard', SimpleNamespace(default_speaker=lambda: devices[0], all_speakers=lambda: devices))
    monkeypatch.setitem(sys.modules, 'numpy', SimpleNamespace())
    assert windows_audio.main(['--list']) == 0
    assert capsys.readouterr().out.strip() == '[{"id": "speaker", "label": "教室耳机", "isDefault": true}]'


def test_embedded_resource_check_does_not_start_gui_or_cloud(monkeypatch):
    if not (runtime.ROOT / 'frontend/dist/index.html').exists():
        pytest.skip('Build frontend before checking embedded resources')
    monkeypatch.setattr(desktop_launcher, 'launch', lambda: pytest.fail('self-test must not open UI'))
    assert desktop_launcher.self_test()['selfTest'] == 'ok'

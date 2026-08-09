import typer
from typer.testing import CliRunner

from experties.plugins import load_plugins

runner = CliRunner()


def _new_test_app() -> typer.Typer:
    """
    A bare typer.Typer() with exactly one command collapses into
    "no subcommand name needed" mode — invoking it runs that one command
    directly, so `runner.invoke(app, ["some-command"])` fails with a
    usage error. The real `experties` app never hits this since it
    already has 8+ built-in commands before any plugin loads. Giving
    test apps a placeholder command keeps them in normal multi-command
    mode, matching how plugins actually get loaded in practice.
    """
    app = typer.Typer()

    @app.command()
    def _placeholder() -> None:
        pass

    return app


def test_missing_plugins_directory_returns_empty_list(tmp_path):
    app = _new_test_app()
    loaded = load_plugins(app, plugins_dir=tmp_path / "does_not_exist")
    assert loaded == []


def test_empty_plugins_directory_returns_empty_list(tmp_path):
    app = _new_test_app()
    loaded = load_plugins(app, plugins_dir=tmp_path)
    assert loaded == []


def test_valid_plugin_is_loaded_and_its_command_actually_works(tmp_path):
    (tmp_path / "greet.py").write_text(
        "def register(app):\n"
        "    @app.command('hello-plugin')\n"
        "    def hello_plugin():\n"
        "        print('hello from plugin')\n"
    )
    app = _new_test_app()
    loaded = load_plugins(app, plugins_dir=tmp_path)
    assert loaded == ["greet.py"]

    result = runner.invoke(app, ["hello-plugin"])
    assert result.exit_code == 0
    assert "hello from plugin" in result.output


def test_plugin_without_register_function_is_skipped_not_crashed(tmp_path):
    (tmp_path / "broken.py").write_text("x = 1\n")
    app = _new_test_app()
    loaded = load_plugins(app, plugins_dir=tmp_path)
    assert loaded == []


def test_plugin_that_raises_is_skipped_but_others_still_load(tmp_path):
    (tmp_path / "aaa_bad.py").write_text(
        "def register(app):\n"
        "    raise RuntimeError('boom')\n"
    )
    (tmp_path / "zzz_good.py").write_text(
        "def register(app):\n"
        "    @app.command('good-cmd')\n"
        "    def good_cmd():\n"
        "        print('ok')\n"
    )
    app = _new_test_app()
    loaded = load_plugins(app, plugins_dir=tmp_path)
    assert loaded == ["zzz_good.py"]

    result = runner.invoke(app, ["good-cmd"])
    assert result.exit_code == 0
    assert "ok" in result.output


def test_plugin_with_syntax_error_is_skipped_but_others_still_load(tmp_path):
    (tmp_path / "aaa_syntax_error.py").write_text("def register(app:\n    this is not valid python\n")
    (tmp_path / "zzz_good.py").write_text(
        "def register(app):\n"
        "    @app.command('good-cmd')\n"
        "    def good_cmd():\n"
        "        pass\n"
    )
    app = _new_test_app()
    loaded = load_plugins(app, plugins_dir=tmp_path)
    assert loaded == ["zzz_good.py"]


def test_files_starting_with_underscore_are_skipped(tmp_path):
    (tmp_path / "_disabled.py").write_text(
        "def register(app):\n"
        "    @app.command('should-not-appear')\n"
        "    def cmd():\n"
        "        pass\n"
    )
    app = _new_test_app()
    loaded = load_plugins(app, plugins_dir=tmp_path)
    assert loaded == []


def test_non_python_files_are_ignored(tmp_path):
    (tmp_path / "notes.txt").write_text("not a plugin")
    app = _new_test_app()
    loaded = load_plugins(app, plugins_dir=tmp_path)
    assert loaded == []


def test_multiple_valid_plugins_all_load_in_sorted_order(tmp_path):
    (tmp_path / "b_plugin.py").write_text(
        "def register(app):\n"
        "    @app.command('cmd-b')\n"
        "    def cmd_b():\n"
        "        pass\n"
    )
    (tmp_path / "a_plugin.py").write_text(
        "def register(app):\n"
        "    @app.command('cmd-a')\n"
        "    def cmd_a():\n"
        "        pass\n"
    )
    app = _new_test_app()
    loaded = load_plugins(app, plugins_dir=tmp_path)
    assert loaded == ["a_plugin.py", "b_plugin.py"]


def test_plugin_can_import_from_experties_package(tmp_path):
    # Plugins run as real modules in this process, so they should be
    # able to reach into the app's own internals (database, rank_engine)
    # exactly like cli.py does.
    (tmp_path / "uses_rank_engine.py").write_text(
        "from experties.rank_engine import get_rank_status\n"
        "\n"
        "def register(app):\n"
        "    @app.command('check-rank')\n"
        "    def check_rank():\n"
        "        status = get_rank_status(20)\n"
        "        print(status.display_name)\n"
    )
    app = _new_test_app()
    loaded = load_plugins(app, plugins_dir=tmp_path)
    assert loaded == ["uses_rank_engine.py"]

    result = runner.invoke(app, ["check-rank"])
    assert result.exit_code == 0
    assert "Mud 2" in result.output
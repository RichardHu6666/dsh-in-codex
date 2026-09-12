"""Keep test state inside the checkout, including on fresh installations."""
import tempfile


def pytest_configure(config):
    if config.option.basetemp is None:
        runtime = config.rootpath / ".runtime"
        runtime.mkdir(exist_ok=True)
        config.option.basetemp = tempfile.mkdtemp(prefix="pytest-", dir=runtime)

import pathlib
import re
import typing as t

from movici_api_client.cli.exceptions import InvalidDirectory

MOVICI_DATADIR_SENTINEL = ".movici_data"


class DataDir:
    datasets: t.Optional[pathlib.Path] = None
    scenarios: t.Optional[pathlib.Path] = None
    views: t.Optional[pathlib.Path] = None

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path

    def iter_datasets(self) -> t.Iterable[pathlib.Path]:
        raise NotImplementedError

    def iter_scenarios(self) -> t.Iterable[pathlib.Path]:
        raise NotImplementedError

    def iter_updates(self, scenario: str) -> t.Iterable[pathlib.Path]:
        raise NotImplementedError

    def iter_views(self, scenario: str) -> t.Iterable[pathlib.Path]:
        raise NotImplementedError

    def ensure_views_dir(self, scenario: str) -> pathlib.Path:
        raise NotImplementedError

    def ensure_simulation_dir(self, scenario: str) -> pathlib.Path:
        raise NotImplementedError

    @staticmethod
    def _ensure_directory(path: pathlib.Path):
        if not path.exists():
            path.mkdir(exist_ok=True, parents=True)
        if not path.is_dir():
            raise InvalidDirectory("not a directory", path)
        return path


class MoviciDataDir(DataDir):
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path

    @property
    def datasets(self):
        return self.path.joinpath("init_data")

    @property
    def scenarios(self):
        return self.path.joinpath("scenarios")

    @property
    def views(self):
        return self.path.joinpath("views")

    @property
    def _sentinel(self):
        return self.path.joinpath(MOVICI_DATADIR_SENTINEL)

    def __eq__(self, other):
        if not isinstance(other, MoviciDataDir):
            return NotImplemented
        return self.path == other.path

    @classmethod
    def resolve_from_subpath(cls, path: t.Union[str, pathlib.Path]) -> t.Optional["MoviciDataDir"]:
        path = pathlib.Path(path).resolve()

        for _ in range(100):
            if path.joinpath(MOVICI_DATADIR_SENTINEL).is_file():
                return cls(path)
            if str(path) == path.anchor:
                break
            path = path.parent

        return None

    def initialize(self):
        if not self.path.exists():
            self.path.mkdir(parents=True, exist_ok=True)
        self.create_tree(exists_ok=True)

    def create_tree(self, exists_ok: bool = False):
        if not self.path.is_dir():
            raise InvalidDirectory("not a directory", self.path)
        self._sentinel.touch()
        self.datasets.mkdir(exist_ok=exists_ok)
        self.scenarios.mkdir(exist_ok=exists_ok)
        self.views.mkdir(exist_ok=exists_ok)

    def iter_datasets(self):
        yield from DatasetsDirectory(self.datasets).iter_datasets()

    def iter_scenarios(self):
        yield from ScenariosDirectory(self.scenarios).iter_scenarios()

    def iter_updates(self, scenario: str):
        yield from UpdatesDirectory(self.scenarios.joinpath(scenario)).iter_updates()

    def iter_views(self, scenario: str):
        yield from ViewsDirectory(self.views.joinpath(scenario)).iter_views()

    def ensure_views_dir(self, scenario: str):
        return self._ensure_directory(self.views.joinpath(scenario))

    def ensure_simulation_dir(self, scenario: str):
        return self._ensure_directory(self.scenarios.joinpath(scenario))


class SimpleDataDirectory(DataDir):
    extensions: t.Optional[t.Collection[str]] = None

    def _iter_files(self):
        if not self.path.is_dir():
            return
        for candidate in self.path.iterdir():
            if not candidate.is_file():
                continue
            if self.extensions is None or candidate.suffix in self.extensions:
                yield candidate

    def iter_datasets(self):
        yield from ()

    def iter_scenarios(self):
        yield from ()

    def iter_updates(self, scenario: str):
        yield from ()

    def iter_views(self, scenario: str):
        yield from ()


class DatasetsDirectory(SimpleDataDirectory):
    extensions = {".json", ".msgpack", ".csv", ".nc", ".tiff", ".tif", ".geotif", ".geotif"}

    @property
    def datasets(self):
        return self.path

    def iter_datasets(self):
        yield from self._iter_files()


class ScenariosDirectory(SimpleDataDirectory):
    extensions = {".json"}

    @property
    def scenarios(self):
        return self.path

    def iter_scenarios(self):
        yield from self._iter_files()

    def iter_updates(self, scenario: str):
        path = self.path.joinpath(scenario)
        yield from UpdatesDirectory(path).iter_updates()

    def ensure_simulation_dir(self, scenario: str):
        return self._ensure_directory(self.scenarios.joinpath(scenario))


class UpdatesDirectory(SimpleDataDirectory):
    extensions = {".json"}

    def iter_updates(self, scenario: t.Optional[str] = None):
        pattern = re.compile(r"t(?P<timestamp>\d+)_(?P<iteration>\d+)_(?P<dataset>\w+)")
        for file in self._iter_files():
            if pattern.match(file.stem):
                yield file

    def ensure_simulation_dir(self, scenario: str):
        return self._ensure_directory(self.path)


class ViewsDirectory(SimpleDataDirectory):
    extensions = {".json"}

    def iter_views(self, scenario: t.Optional[str] = None):
        yield from self._iter_files()

    def ensure_views_dir(self, scenario: str):
        return self._ensure_directory(self.path)

"""Public Creative Workshop package boundary."""

from .errors import (
    WorkshopError,
    WorkshopInstallError,
    WorkshopPackageError,
    WorkshopRegistryError,
    WorkshopReleaseError,
)
from .install_store import InstalledModuleState
from .installer import WorkshopInstaller
from .models import InspectedWorkshopPackage, WorkshopManifestV1
from .package_validator import (
    extract_inspected_package,
    inspect_workshop_package,
)
from .registry_client import (
    RegistryClient,
    RegistryFetchResponse,
    load_registry_keys,
)
from .release_client import (
    download_registry_package,
    resolve_github_release_package,
)

__all__ = [
    "InspectedWorkshopPackage",
    "InstalledModuleState",
    "RegistryClient",
    "RegistryFetchResponse",
    "WorkshopError",
    "WorkshopInstallError",
    "WorkshopInstaller",
    "WorkshopManifestV1",
    "WorkshopPackageError",
    "WorkshopRegistryError",
    "WorkshopReleaseError",
    "extract_inspected_package",
    "inspect_workshop_package",
    "load_registry_keys",
    "download_registry_package",
    "resolve_github_release_package",
]

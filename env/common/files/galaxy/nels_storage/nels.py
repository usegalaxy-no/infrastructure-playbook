import os
import functools
import tempfile
from typing import Optional, Union, Tuple, List, Any

import requests
import galaxy.util.json as json

try:
    from fs.sshfs import SSHFS
except ImportError:
    SSHFS = None

import fs
from fs.enums import ResourceType
from typing_extensions import Unpack

from . import (
    AnyRemoteEntry,
    FilesSourceOptions,
    FilesSourceProperties,
)
from ._pyfilesystem2 import PyFilesystem2FilesSource
from galaxy.exceptions import ConfigurationError

# NeLS Storage-specific options that should be set in "config/file_sources_conf.yml"
#
#  nels_config: str (file path)
#      The location of a configuration file in INI-format that contains the base "API_URL" for the NeLS Storage API
#      along with a "CLIENT_KEY" and "CLIENT_SECRET" used for authentication against the API
#  userid: str
#      A unique ID for each user (templated from the user profile) that can be used as argument
#      to identify the user when querying the NeLS Storage API. Suggested value:  ${user.email}
#  homedir: str (file path)
#      The directory on the storage server that will serve as the home (and top-level) directory for the user.
#      This path can contain the expression "<user>" which will be replaced by the user's corresponding OS username
#      on the storage server. (Note that this will not be the same as "userid" above.)
#  ignore_hidden: boolean
#      If TRUE, hidden files will not be shown in the UI
#
#
# Example:
# ========
#
# - type: nels
#   id: nels_storage
#   label: "NeLS Storage"
#   doc: ""
#   writable: true
#   nels_config: "/srv/galaxy/server/tool-data/nels_storage_config.loc"
#   userid: ${user.email}
#   homedir: "/nels/users/<user>"
#   ignore_hidden: true

class NeLSFilesSource(PyFilesystem2FilesSource):
    plugin_type = "nels"
    required_module = SSHFS
    required_package = "fs.sshfs"

    def _list(
        self,
        path="/",
        recursive=False,
        user_context=None,
        opts: Optional[FilesSourceOptions] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        query: Optional[str] = None,
        sort_by: Optional[str] = None,
    ) -> Tuple[List[dict], int]:
        """Return list of entries and total count."""
        # This method is based on the superclass implementation, but I have included an option to ignore hidden files
        # and also added code to clean up afterwards (to remove temporary SSH key file)
        try:
            with self._open_fs(user_context=user_context, opts=opts) as h:
                ignore_hidden = self._props.get("ignore_hidden")

                if recursive: # this mode returns everything (including subdirs) without applying pagination or query filtering
                    recursive_result: List[AnyRemoteEntry] = []
                    for p, dirs, files in h.walk(path, namespaces=["details"]):
                        to_dict = functools.partial(self._resource_info_to_dict, p, h)
                        recursive_result.extend(map(to_dict, dirs))
                        recursive_result.extend(map(to_dict, files))
                    if ignore_hidden:
                        recursive_result = [ i for i in recursive_result if not i["name"].startswith(".") ]
                    return recursive_result, len(recursive_result)

                # Non-recursive case. Return contents of a single directory and apply pagination and query filtering
                page = self._to_page(limit, offset)
                filter = self._query_to_filter(query)
                result = h.filterdir(path, namespaces=["details"], page=page, files=filter, dirs=filter)
                to_dict = functools.partial(self._resource_info_to_dict, path, h)
                items = list(map(to_dict, result))

                if ignore_hidden:
                    items = [i for i in items if not i["name"].startswith(".")]

                # Correct total count (respecting ignore_hidden option)
                all_items = h.filterdir(path, namespaces=["basic"], files=filter, dirs=filter,)
                if ignore_hidden:
                    count = sum(1 for i in all_items if not i.name.startswith("."))
                else:
                    count = sum(1 for _ in all_items)

                return items, count

        except fs.errors.PermissionDenied as e:
            raise AuthenticationRequired(f"Permission Denied. Reason: {e}. Please contact the Elixir Norway helpdesk if the problem persists.")

        except fs.errors.FSError as e:
            raise MessageException(f"Problem listing file source path {path}. Reason: {e}") from e

        finally:
            if "h" in locals() and h:
                self._cleanup(h)

    # This method replaces the version from the superclass to correctly
    # treat symlinks to directories as directories rather than regular files.
    # Note that the signature has one additional input argument
    def _resource_info_to_dict(self, dir_path, h, resource_info) -> AnyRemoteEntry:
        name = resource_info.name
        path = os.path.join(dir_path, name)
        uri = self.uri_from_path(path)

        size = resource_info.size
        created = resource_info.created
        is_dir = resource_info.is_dir
        is_link = resource_info.type == ResourceType.symlink

        if is_link:
            try:
                # get more info about symlink from "details" namespace to determine whether it points to a directory
                link_info = h.getinfo(path, namespaces=["details", "access", "link"])
                is_dir = link_info.is_dir
                size = link_info.size
            except Exception:
                # Errors can stem from symlinks pointing to non-existent files/directories.
                # Ignore the error here and treat these as regular files
                pass

        if is_dir:
            return {
                "class": "Directory",
                "name": name,
                "uri": uri,
                "path": path,
            }
        else:
            return {
                "class": "File",
                "name": name,
                "size": size,
                "ctime": self.to_dict_time(created),
                "uri": uri,
                "path": path,
            }


    def _realize_to(self, source_path, native_path, user_context=None, opts: Optional[FilesSourceOptions] = None):
        h = None
        with open(native_path, "wb") as write_file:
            try:
                h = self._open_fs(user_context=user_context, opts=opts)
                h.download(source_path, write_file)
            finally:
                if h:
                    self._cleanup(h)


    def _write_from(self, target_path, native_path, user_context=None, opts: Optional[FilesSourceOptions] = None):
        h = None
        with open(native_path, "rb") as read_file:
            try:
                h = self._open_fs(user_context=user_context, opts=opts)
                dirname = fs.path.dirname(target_path)
                if not h.isdir(dirname):
                    h.makedirs(dirname)
                h.upload(target_path, read_file)
            finally:
                if h:
                    self._cleanup(h)

    # -----------------------------
    # OPEN FILESYSTEM (SSH)
    # -----------------------------
    def _open_fs(self, user_context=None, opts: Optional[FilesSourceOptions] = None):
        props = self._serialization_props(user_context)
        extra_props: Union[FilesSourceProperties, dict] = (
            opts.extra_props or {} if opts else {}
        )
        # Some of the properties from the YAML config are not expected by SSHFS,
        # so we must remove (pop) them here or else an exception will be raised
        nels_config_file = props.pop("nels_config")
        homedir = props.pop("homedir")
        username = props.pop("userid")
        props.pop("ignore_hidden", None)

        config = self._configure_nels_api_connection(nels_config_file)

        host, nelsUser, sshKey = self._get_nels_ssh_credentials(
            username,
            config["API_URL"],
            config["CLIENT_KEY"],
            config["CLIENT_SECRET"],
        )

        props["host"] = host

        # Safe temporary key file
        tmp = tempfile.NamedTemporaryFile(delete=False)
        keyfilename = tmp.name
        tmp.close()

        with open(keyfilename, "w") as sshFile:
            sshFile.write(sshKey)

        os.chmod(keyfilename, 0o600)

        props["pkey"] = keyfilename
        props["user"] = nelsUser

        handle = SSHFS(**{**props, **extra_props})

        homedir = homedir.replace("<user>", nelsUser)
        handle = handle.opendir(homedir)

        # Store keyfile path for later cleanup
        handle.nels_keyfile = keyfilename

        return handle

    # -----------------------------
    # CONFIG PARSING
    # -----------------------------
    def _configure_nels_api_connection(self, configfile):
        config = {}
        with open(configfile) as f:
            for line in f:
                if "=" in line:
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()

        for attr in ("API_URL", "CLIENT_KEY", "CLIENT_SECRET"):
            if attr not in config:
                raise ConfigurationError(f"Missing setting '{attr}' in NeLS Storage configuration file")

        return config

    # -----------------------------
    # FETCH SSH CREDENTIALS
    # -----------------------------
    def _get_nels_ssh_credentials(self, user_id, api_url, client_key, client_secret):
        url = f"{api_url}/federated/{user_id}"
        response = requests.get(url, auth=(client_key, client_secret))

        if response.status_code == requests.codes.ok:
            json_response = response.json()
            return [
                json_response["hostname"],
                json_response["username"],
                json_response["key-rsa"],
            ]
        else:
            raise Exception(f"NeLS Storage API error: HTTP response code {response.status_code} [{url}]")

    # -----------------------------
    # CLEANUP
    # -----------------------------
    def _cleanup(self, h):
        """Delete temporary SSH key file."""
        if not h:
            return

        keyfile = getattr(h, "nels_keyfile", None)
        if keyfile and os.path.exists(keyfile):
            try:
                os.remove(keyfile)
            except Exception:
                pass


__all__ = ("NeLSFilesSource",)

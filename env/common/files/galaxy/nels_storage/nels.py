import os
import galaxy.util.json as json
import requests
import functools
import tempfile
from requests.auth import HTTPBasicAuth


try:
    from fs.sshfs import SSHFS
except ImportError:
    SSHFS = None

from ._pyfilesystem2 import PyFilesystem2FilesSource
from galaxy.exceptions import ConfigurationError
from fs.enums import ResourceType

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
#   homedir: "/elixir-chr/nels/users/<user>"
#   ignore_hidden: true


class NeLSFilesSource(PyFilesystem2FilesSource):
    plugin_type = "nels"
    required_module = SSHFS
    required_package = "fs.sshfs"

    def _list(self, path="/", recursive=False, user_context=None):
        """
        Return dictionary of 'Directory's and 'File's.
        """
        # This method is copied verbatim from the superclass, but I have included an option to ignore hidden files
        # and also added code to clean up afterwards (to remove temporary SSH key file)

        try:
            with self._open_fs(user_context=user_context) as h:
                if recursive:
                    res = []
                    for p, dirs, files in h.walk(path):
                        to_dict = functools.partial(self._resource_info_to_dict, p)
                        res.extend(map(to_dict, dirs))
                        res.extend(map(to_dict, files))
                    return res
                else:
                    res = h.scandir(path, namespaces=['details'])
                    to_dict = functools.partial(self._resource_info_to_dict, path, h)
                    result = list(map(to_dict, res))
                    if (self._props['ignore_hidden']):
                        result = list(filter(lambda x: not x['name'].startswith('.'), result)) # skip files whose names start with a dot
                    return result
        finally:
            self._cleanup(h)

            
    def _resource_info_to_dict(self, dir_path, h, resource_info):
        name = resource_info.name
        path = os.path.join(dir_path, name)
        uri = self.uri_from_path(path)
        size = resource_info.size,
        created = resource_info.created
        is_dir = resource_info.is_dir
        is_link = (resource_info.type==ResourceType.symlink)
        
        if is_link: 
            link_info = h.getinfo(path, namespaces=['details','access','link']) # get info about symlink to determine whether it points to a directory
            is_dir = link_info.is_dir
            size = link_info.size # return size of target file and not of the symlink itself
           
        if is_dir:
            return {"class": "Directory", "name": name, "uri": uri, "path": path}
        else:
            return {
                "class": "File",
                "name": name,
                "size": size,
                "ctime": self.to_dict_time(created),
                "uri": uri,
                "path": path
            }


    def _realize_to(self, source_path, native_path, user_context=None):
        with open(native_path, 'wb') as write_file:
            try:
                h = self._open_fs(user_context=user_context)
                h.download(source_path, write_file)
            finally:
                self._cleanup(h)

            
    def _write_from(self, target_path, native_path, user_context=None):
        with open(native_path, 'rb') as read_file:
            try:
                h = self._open_fs(user_context=user_context)
                h.upload(target_path, read_file)
            finally:
                self._cleanup(h)

            
            
    def _open_fs(self, user_context):
        props = self._serialization_props(user_context)
        # Some of the properties from the YAML config are not expected by SSHFS, so we must remove (pop) them here or else an exception will be raised
        nels_config_file = props.pop('nels_config')
        homedir = props.pop('homedir')
        username = props.pop('userid')
        props.pop("ignore_hidden") 
        
        config = self._configure_nels_api_connection(nels_config_file)
        [host,nelsUser,sshKey] = self._get_nels_ssh_credentials(username,config['API_URL'],config['CLIENT_KEY'],config['CLIENT_SECRET'])        
        props['host'] = host
        
        keyfilename = tempfile.NamedTemporaryFile().name
        with open(keyfilename, 'w') as sshFile:
            sshFile.write(sshKey)
        os.system('chmod 0600 %s' % keyfilename)
        props['pkey'] = keyfilename
        props['user'] = nelsUser

        handle = SSHFS(**props)
        homedir = homedir.replace("<user>",nelsUser) # home directories are named after the NeLS user
        handle = handle.opendir(homedir)
        
        # I store the location of the temporary SSH key file in the SSHFS object in order to pass this information back to he calling function
        # The key file should be deleted again as soon as possible
        handle.nels_keyfile = keyfilename 
        return handle


    def _configure_nels_api_connection(self, configfile):
        config = {}
        with open(configfile) as f:
            lines = f.readlines()
            for line in lines:
                if ('=' in line):
                    parts = line.split("=", 1)
                    config[parts[0].strip()] = parts[1].strip()
        for attr in ('API_URL','CLIENT_KEY','CLIENT_SECRET'):
            if not attr in config:
                raise ConfigurationError("Missing setting '%s' in NeLS Storage configuration file" % attr)
        return config


    def _get_nels_ssh_credentials(self, user_id, api_url, client_key, client_secret):
        url = api_url + "/federated/" + str(user_id) # This API endpoint will accept both FEIDE and NeLS IDs 
        response =  requests.get(url, auth=(client_key, client_secret))
        if(response.status_code == requests.codes.ok):
            json_response = response.json()
            return [json_response['hostname'],json_response['username'],json_response['key-rsa']]
        else:
            raise Exception("NeLS Storage API error: HTTP response code %s [%s]" % (str(response.status_code),url))        


        
    def _cleanup(self, h):
        """Delete temporary SSH key file."""
        keyfile = h.nels_keyfile if h else None
        if os.path.exists(keyfile):
            os.remove(keyfile)
            
__all__ = ("NeLSFilesSource",)

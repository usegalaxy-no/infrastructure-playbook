#Playbooks

These are the playbooks for installing and maintaining the usegalaxy.no setup.

The playbooks are distributed as:

1. base.yml: base system (apache, postgresql, etc)
2. galaxy.yml: galaxy server, branding and configuration
3. backend.yml: pulsar and friends for the backend compute
4. galaxy-content.yml: install tools and workflows

To ease configuration of the playbooks, key information shared between multiple playbooks are stored in **group_vars/global.yml**. 


As some of the var files include passwords and api-keys they are encrypted using ansible-vault. These will be decrypted at runtime, either by providing the password when asked or using a password file. See the [security section]{#Security) below for more information or [ansible-vault](https://docs.ansible.com/ansible/latest/user_guide/vault.html).

Each of the playbooks contain multiple plays that can be executed independenty using the tag for the playbook. 

```
# this will only run the apache sub-play of this playbook
ansible-playbook --tags apache base.yml 
``` 





##Base system

This will install the base system required for the main usegalaxy server. Several of the components are optional but include:

0. base requirements eg bzip2, git, etc
1. postgresql (done)
3. certbot (done)
2. apache (done)
2. rabbitmq (later, depends on elastic compute solution)
3. slurm single node (Later)

Make a copy of group_vars/global.yml.sample

```bash
cp group_vars/global.yml.sample  group_vars/global.yml

#Edit values in file

# to encrypt file
ansible-vault encrypt group_vars/global.yml

#You can configure ansible.cfg to make this easier
[default]
# will ask for password when running ansible-password
ask_vault_pass = true 

# Will read the vault password from file
vault_password_file = "File-of-secrest" 

```
Alternatively you can encrypt variables and paste the result into the yaml file

```bash
ansible-vault encrypt_string --vault-password-file vault_password  --name 'galaxy_db_passwd' 'super-secret'

galaxy_db_passwd: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          36633963313039613435326430643565346130633639383262653239653336326261323135306537
          3961316139623533313932326233633137363730363966620a313732626136333535366563313137
          62343137386633666233646638346665313664653263613364626166666462343034616533383261
          3034353862313535620a343635646137623161316165383739626534386265313530323462343835
          3665
Encryption successful

# paste 
```

it is possible to just run one, or more parts of a playbook using the tags

```bash
# To only run  the database part of the playbook
ansible-playbook base_applications.yml --tags 'database'

```


##Galaxy
This will install and configure galaxy along with conda and special configurations eg: authentication 

1. galaxy
2. conda
3. supervisor 
3. branding eg: frontpage and colours
4. configurations
5. cvmfs

For branding of the galaxy all files in templates/galaxy/static/ are copied to the galaxy-server/static/


##Pulsar backend

This will be done in uh-iaas initially until we know where this will be used in production.


##Tools

Install tools in galaxy 


##Workflows

Install tools in galaxy




## Security



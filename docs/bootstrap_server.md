
```
sudo yum install -y epel-release 

sudo yum install -y  git python3 bzip2

git clone git@github.com:elixir-no-nels/usegalaxy.git

cd usegalaxy
virtualenv -p python3 venv
source venv/bin/activate
pip install ansible

cd playbooks
# Install roles
ansible-galaxy install -p roles -r requirements.yml

ansible-playbook -i hosts playbook.yml

```


Needs ansible version >=  2.7




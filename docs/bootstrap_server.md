Note: Needs ansible version >=  2.7


```

git clone git@github.com:elixir-no-nels/usegalaxy.git

cd usegalaxy
virtualenv -p python3 venv
source venv/bin/activate
pip install ansible

cd playbooks
# Install requirement roles
ansible-galaxy install -p roles -r requirements.yml

# edit hosts file to point to the correct hosts.
# run playbook
ansible-playbook -i hosts playbook.yml



```







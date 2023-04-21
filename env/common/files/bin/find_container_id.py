#!/srv/galaxy/venv/bin/python3
# --------------------------------------------------------------------------------------------
## NB! Since this script relies on dependencies included in Galaxy, you must either run it 
## directly as an executable (with the python version specified by the shebang in the first line)
## or else you must first activate Galaxy's virtual environment with:
##
##     source /srv/galaxy/venv/bin/activate
##
# --------------------------------------------------------------------------------------------
# New in version 3:
#   - it handles all macros and tokens automatically, even if they are defined in other files.
#

import sys
import argparse

sys.path.append('/srv/galaxy/server/lib/')

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.deps.mulled.util import build_target, v2_image_name

def main(argv=None):
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('tool', metavar="TOOL", default=None, help="Path to tool to build mulled image for.")
    args = parser.parse_args()
    tool_source = get_tool_source(args.tool)
    requirements, containers = tool_source.parse_requirements_and_containers()
    container_requirements = [c.to_dict() for c in containers]

    if (requirements):
        targets = requirements_to_mulled_targets(requirements)
        has_version=0
        print("Tool requirements:")
        for requirement in requirements:
            if (requirement.version):
                has_version = has_version+1
                print(f"  - {requirement.name} ({requirement.version})")
            else:
                print(f"  - {requirement.name} (no version specified)")

        print("\nContainer image name:")
        container_name = v2_image_name(targets)
        if (has_version == 0):
            container_name = container_name+":0"  # if version is missing, Galaxy will break!
        else:
            container_name = container_name+"-0" # assuming no build is specified
        print("  "+container_name)
    elif (container_requirements):
        if (len(container_requirements)==1):
            container_type = container_requirements[0]['type']
            container_path = container_requirements[0]['identifier']
            print(f"The tool does not specify any package requirements, but rather the {container_type}-container: {container_path}")
        elif (len(container_requirements)>1):
            print(f"The tool does not specify any package requirements, but rather the following containers:")
            for cr in container_requirements:
                container_type = cr['type']
                container_path = cr['identifier']
                print(f"  - {container_path} [{container_type}]")

    else:
        print("No package requirements found for tool!")
        print("The tool will be run with the default container: /srv/galaxy/containers/galaxy-python.sif")


def requirements_to_mulled_targets(requirements):
    """Convert Galaxy's representation of requirements into mulled Target objects.

    Only package requirements are retained.
    """
    package_requirements = [r for r in requirements if r.type == "package"]
    targets = [build_target(r.name, r.version) for r in package_requirements]
    return targets


__all__ = ("main", "requirements_to_mulled_targets")


if __name__ == '__main__':
    main()



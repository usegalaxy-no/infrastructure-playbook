#!/usr/bin/env python3
#

import os
import argparse


def main():

    parser = argparse.ArgumentParser(description='get owner and permission of a dir in telegraf format')
    parser.add_argument('-D', '--dirs-only', action="store_true",  help="Only report directories")
    parser.add_argument('dirs', nargs='+', help="directories to report information for")

    args = parser.parse_args()


#    dir = "/srv/galaxy/server/dependencies/"
#    dir = '/etc/'
    for dir in args.dirs:
        if args.dirs_only and not os.path.isdir( dir ):
            continue
        if not os.path.isdir( dir ) and  not os.path.isfile( dir ):
            #print(f"dir_permission,dir={dir} ")
            continue
        else:
            dir = dir.rstrip("/")

            st = os.stat(dir)
            u,g,o = oct(st.st_mode)[-3:]
            perm = oct(st.st_mode)[-4:]
            print(f"dir_permission,dir={dir} uid={st.st_uid},gid={st.st_gid},up={u},gp={g},op={o},perm={perm}")




if __name__ == "__main__":
    main()



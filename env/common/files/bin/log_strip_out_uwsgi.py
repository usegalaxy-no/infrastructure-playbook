#!/usr/bin/env python3

import argparse
import sys
import pprint as pp
import gzip
import re
import os

def open_outstream( outfile:str=None) -> int:
    fh = sys.stdout

    if outfile is not None:
        fh = open(outfile, 'w')

    return fh



def process_logfile(infile:str, mask:bool=False, outfile:str=None) -> None:


    in_fh = open(infile, 'r')
    out_fh = open_outstream(outfile)

    for line in in_fh:
        if re.search(r'uwsgi: \d+\.\d+\.\d+\.\d+', line) or re.search(r'uwsgi: \[pid:.* \d+\.\d+\.\d+\.\d+ ', line):
            if mask:
                line = re.sub( r' \d+\.\d+\.\d+\.\d+ ', 'XXX.XXX.XXX.XXX', line)
                out_fh.write( line )
        else:
            out_fh.write( line )

def main():
    parser = argparse.ArgumentParser(description='ehosd: the ehos daemon to be run on the master node ')

    parser.add_argument('-o', '--outfile', default=None, help="file to write to, default stdout")
    parser.add_argument('-m', '--mask', default=False, action='store_true',  help="mask rather than strip IP")
    parser.add_argument('-r', '--replace', default=False, action='store_true',  help="replace original file with altered one")
    parser.add_argument('infile', metavar='infiles', nargs=1, help="infile to mask uwsgi IP's in")

    args = parser.parse_args()
    args.infile = args.infile[0]

    if not os.path.isfile( args.infile ):
        sys.exit()


    if args.replace:
        tempfile = "{}.tmp".format(args.infile)
        os.rename(args.infile, tempfile)
        args.infile, args.outfile = tempfile, args.infile


    process_logfile( infile=args.infile, mask=args.mask, outfile=args.outfile)


    if args.replace:
        os.remove( tempfile )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys

from ros_buildfarm.argument import add_argument_output_dir
from ros_buildfarm.catkin_workspace import call_catkin_make_isolated
from ros_buildfarm.catkin_workspace import clean_workspace
from ros_buildfarm.catkin_workspace import ensure_workspace_exists
from ros_buildfarm.common import Scope
from ros_buildfarm.rosdoc_tag_index import build_tagfile


def main(argv=sys.argv[1:]):
    parser = argparse.ArgumentParser(
        description="Invoke 'rosdoc_lite' on each package of a workspace")
    parser.add_argument(
        '--rosdistro-name',
        required=True,
        help='The name of the ROS distro to identify the setup file to be '
             'sourced (if available)')
    parser.add_argument(
        '--os-code-name',
        required=True,
        help="The OS code name (e.g. 'trusty')")
    parser.add_argument(
        '--arch',
        required=True,
        help="The architecture (e.g. 'amd64')")
    parser.add_argument(
        '--workspace-root',
        required=True,
        help='The root path of the workspace to compile')
    parser.add_argument(
        '--rosdoc-lite-dir',
        required=True,
        help='The root path of the rosdoc_lite repository')
    parser.add_argument(
        '--rosdoc-tag-index-dir',
        required=True,
        help='The root path of the rosdoc_tag_index repository')
    parser.add_argument(
        'pkg_tuples',
        nargs='*',
        help='A list of package tuples in topological order, each ' +
             'containing the name and relative path separated by a colon')
    add_argument_output_dir(parser, required=True)
    args = parser.parse_args(argv)

    ensure_workspace_exists(args.workspace_root)
    clean_workspace(args.workspace_root)

    rc = call_catkin_make_isolated(
        args.rosdistro_name, args.workspace_root,
        ['--install', '--cmake-args', '-DCATKIN_SKIP_TESTING=1',
         '--catkin-make-args', '-j1'])
    # TODO compile error should still allow to generate doc from static parts
    if rc:
        return rc

    source_space = os.path.join(args.workspace_root, 'src')
    for pkg_tuple in args.pkg_tuples:
        pkg_name, pkg_subfolder = pkg_tuple.split(':', 1)
        with Scope('SUBSECTION', 'rosdoc_lite - %s' % pkg_name):
            pkg_path = os.path.join(source_space, pkg_subfolder)

            pkg_doc_path = os.path.join(args.output_dir, 'api_rosdoc', pkg_name)
            pkg_tags_path = os.path.join(
                args.output_dir, 'tags', '%s.tag' % pkg_name)

            source_cmd = [
                '.',
                os.path.join(args.workspace_root, 'install_isolated', 'setup.sh'),
            ]
            rosdoc_lite_cmd = [
                os.path.join(args.rosdoc_lite_dir, 'scripts', 'rosdoc_lite'),
                pkg_path,
                '-o', pkg_doc_path,
                '-g', pkg_tags_path,
                '-t', os.path.join(
                    args.output_dir, 'rosdoc_tags', pkg_name, 'rosdoc_tags.yaml'),
            ]
            print("Invoking `rosdoc_lite` for package '%s': %s" %
                  (pkg_name, ' '.join(rosdoc_lite_cmd)))
            pkg_rc = subprocess.call(
                [
                    'sh', '-c',
                    ' '.join(source_cmd) +
                    ' && ' +
                    'PYTHONPATH=%s/src:$PYTHONPATH ' % args.rosdoc_lite_dir +
                    ' '.join(rosdoc_lite_cmd)
                ], stderr=subprocess.STDOUT, cwd=pkg_path)
            if pkg_rc:
                rc = pkg_rc

    return rc


if __name__ == '__main__':
    sys.exit(main())

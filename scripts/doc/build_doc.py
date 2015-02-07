#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import yaml

from ros_buildfarm.argument import add_argument_output_dir
from ros_buildfarm.catkin_workspace import call_catkin_make_isolated
from ros_buildfarm.catkin_workspace import clean_workspace
from ros_buildfarm.catkin_workspace import ensure_workspace_exists
from ros_buildfarm.common import Scope
from ros_buildfarm.rosdoc_index import RosdocIndex


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
        '--rosdoc-index-dir',
        required=True,
        help='The root path of the rosdoc_index folder')
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

    rosdoc_index = RosdocIndex([
        os.path.join(args.output_dir, args.rosdistro_name),
        os.path.join(args.rosdoc_index_dir, args.rosdistro_name)])

    sys.path.insert(0, os.path.join(args.rosdoc_lite_dir, 'src'))
    from rosdoc_lite import get_generator_output_folders

    source_space = os.path.join(args.workspace_root, 'src')
    for pkg_tuple in args.pkg_tuples:
        pkg_name, pkg_subfolder = pkg_tuple.split(':', 1)
        with Scope('SUBSECTION', 'rosdoc_lite - %s' % pkg_name):
            pkg_path = os.path.join(source_space, pkg_subfolder)

            pkg_doc_path = os.path.join(
                args.output_dir, 'api_rosdoc', pkg_name)
            pkg_tag_path = os.path.join(
                args.output_dir, 'symbols', '%s.tag' % pkg_name)

            source_cmd = [
                '.',
                os.path.join(
                    args.workspace_root, 'install_isolated', 'setup.sh'),
            ]
            rosdoc_lite_cmd = [
                os.path.join(args.rosdoc_lite_dir, 'scripts', 'rosdoc_lite'),
                pkg_path,
                '-o', pkg_doc_path,
                '-g', pkg_tag_path,
                '-t', os.path.join(
                    args.output_dir, 'rosdoc_tags', pkg_name,
                    'rosdoc_tags.yaml'),
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

            # only if rosdoc runs generates a symbol file
            # create the corresponding location file
            if os.path.exists(pkg_tag_path):
                data = {
                    'docs_url': '../../../api/%s/html' % pkg_name,
                    'location': '%s/symbols/%s.tag' %
                    (args.rosdistro_name, pkg_name),
                    'package': pkg_name,
                }

                # fetch generator specific output folders from rosdoc_lite
                output_folders = get_generator_output_folders(pkg_path)
                for generator, output_folder in output_folders.items():
                    data['%s_output_folder' % generator] = output_folder

                rosdoc_index.locations[pkg_name] = [data]

            #

            # add_canonical_link(
            #     pkg_doc_path,
            #     "%s/%s/api/%s" % (homepage, ros_distro, package))

            #

            # merge manifest.yaml files
            rosdoc_manifest_yaml_file = os.path.join(
                pkg_doc_path, 'manifest.yaml')
            job_manifest_yaml_file = os.path.join(
                args.output_dir, 'manifests', pkg_name, 'manifest.yaml')
            with open(rosdoc_manifest_yaml_file, 'r') as h:
                rosdoc_data = yaml.load(h)
            with open(job_manifest_yaml_file, 'r') as h:
                job_data = yaml.load(h)
            rosdoc_data.update(job_data)
            with open(rosdoc_manifest_yaml_file, 'w') as h:
                yaml.safe_dump(rosdoc_data, h, default_flow_style=False)

    rosdoc_index.write_modified_data(
        args.output_dir, ['locations'])

    return rc


if __name__ == '__main__':
    sys.exit(main())

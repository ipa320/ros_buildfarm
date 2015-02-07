#!/usr/bin/env python3

from apt import Cache
import argparse
import copy
import os
import re
import sys
import time
import yaml

from catkin_pkg.packages import find_packages
from catkin_pkg.topological_order import topological_order_packages
from rosdep2 import create_default_installer_context
from rosdep2.catkin_support import get_catkin_view
from rosdep2.catkin_support import resolve_for_os
from rosdistro import get_distribution_file
from rosdistro import get_index
from rosdistro import get_index_url

from ros_buildfarm.argument import add_argument_build_name
from ros_buildfarm.argument import \
    add_argument_distribution_repository_key_files
from ros_buildfarm.argument import add_argument_distribution_repository_urls
from ros_buildfarm.argument import add_argument_dockerfile_dir
from ros_buildfarm.argument import add_argument_output_dir
from ros_buildfarm.argument import add_argument_repository_name
from ros_buildfarm.argument import add_argument_force
from ros_buildfarm.common import get_binary_package_versions
from ros_buildfarm.common import get_debian_package_name
from ros_buildfarm.common import get_distribution_repository_keys
from ros_buildfarm.common import get_user_id
from ros_buildfarm.common import Scope
from ros_buildfarm.doc_job import get_doc_job_name
from ros_buildfarm.git import get_hash
from ros_buildfarm.rosdoc_index import RosdocIndex
from ros_buildfarm.templates import create_dockerfile
from ros_buildfarm.templates import expand_template


def main(argv=sys.argv[1:]):
    parser = argparse.ArgumentParser(
        description="Generate a 'Dockerfile' for the doc job")
    parser.add_argument(
        '--rosdistro-name',
        required=True,
        help='The name of the ROS distro to identify the setup file to be '
             'sourced')
    add_argument_build_name(parser, 'doc')
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
    add_argument_repository_name(parser)
    parser.add_argument(
        '--os-name',
        required=True,
        help="The OS name (e.g. 'ubuntu')")
    parser.add_argument(
        '--os-code-name',
        required=True,
        help="The OS code name (e.g. 'trusty')")
    parser.add_argument(
        '--arch',
        required=True,
        help="The architecture (e.g. 'amd64')")
    add_argument_distribution_repository_urls(parser)
    add_argument_distribution_repository_key_files(parser)
    add_argument_force(parser)
    add_argument_output_dir(parser, required=True)
    add_argument_dockerfile_dir(parser)
    args = parser.parse_args(argv)

    with Scope('SUBSECTION', 'packages'):
        # find packages in workspace
        source_space = os.path.join(args.workspace_root, 'src')
        print("Crawling for packages in workspace '%s'" % source_space)
        pkgs = find_packages(source_space)

        pkg_names = [pkg.name for pkg in pkgs.values()]
        print('Found the following packages:')
        for pkg_name in sorted(pkg_names):
            print('  -', pkg_name)

        maintainer_emails = set([])
        for pkg in pkgs.values():
            for m in pkg.maintainers:
                maintainer_emails.add(m.email)
        if maintainer_emails:
            print('Package maintainer emails: %s' %
                  ' '.join(sorted(maintainer_emails)))

    rosdoc_index = RosdocIndex(
        [os.path.join(args.rosdoc_index_dir, args.rosdistro_name)])

    with Scope('SUBSECTION', 'determine need to run documentation generation'):
        # compare hashes to determine if documentation needs to be regenerated
        current_hashes = {}
        current_hashes['ros_buildfarm'] = 1  # increase to retrigger doc jobs
        current_hashes['rosdoc_lite'] = get_hash(args.rosdoc_lite_dir)
        repo_dir = os.path.join(
            args.workspace_root, 'src', args.repository_name)
        # TODO handle non-git repositories
        current_hashes[args.repository_name] = get_hash(repo_dir)
        print('Current repository hashes: %s' % current_hashes)
        tag_index_hashes = rosdoc_index.hashes.get(args.repository_name, {})
        print('Stored repository hashes: %s' % tag_index_hashes)
        skip_doc_generation = current_hashes == tag_index_hashes

    if skip_doc_generation:
        print('No changes to the source repository or any tooling repository')

        if not args.force:
            print('Skipping generation of documentation')

            # create stamp files
            print('Creating marker files to identify that documentation is ' +
                  'up-to-date')
            create_stamp_files(pkg_names, os.path.join(args.output_dir, 'api'))

            return 0

        print("But job was started with the 'force' parameter set")

    else:
        print('The source repository and/or a tooling repository has changed')

    print('Running generation of documentation')
    rosdoc_index.hashes[args.repository_name] = current_hashes
    rosdoc_index.write_modified_data(args.output_dir, ['hashes'])

    # create stamp files
    print('Creating marker files to identify that documentation is ' +
          'up-to-date')
    create_stamp_files(pkg_names, os.path.join(args.output_dir, 'api_rosdoc'))

    index = get_index(get_index_url())
    dist_file = get_distribution_file(index, args.rosdistro_name)
    assert args.repository_name in dist_file.repositories
    valid_package_names = \
        set(pkg_names) | set(dist_file.release_packages.keys())

    # update package deps and metapackage deps
    with Scope('SUBSECTION', 'updated rosdoc_index information'):
        for pkg in pkgs.values():
            depends = _get_build_run_doc_dependencies(pkg)
            ros_dependency_names = sorted(set([
                d.name for d in depends if d.name in valid_package_names]))

            rosdoc_index.set_forward_deps(pkg.name, ros_dependency_names)
            if not pkg.is_metapackage():
                ros_dependency_names = None
            rosdoc_index.set_metapackage_deps(
                pkg.name, ros_dependency_names)
        rosdoc_index.write_modified_data(
            args.output_dir, ['deps', 'metapackage_deps'])

    # generate changelog html from rst
    package_names_with_changelogs = set([])
    with Scope('SUBSECTION', 'generate changelog html from rst'):
        for pkg_path, pkg in pkgs.items():
            abs_pkg_path = os.path.join(source_space, pkg_path)
            assert os.path.exists(os.path.join(abs_pkg_path, 'package.xml'))
            changelog_file = os.path.join(abs_pkg_path, 'CHANGELOG.rst')
            if os.path.exists(changelog_file):
                print(("Package '%s' contains a CHANGELOG.rst, generating " +
                       "html") % pkg.name)
                package_names_with_changelogs.add(pkg.name)

                with open(changelog_file, 'r') as h:
                    rst_code = h.read()
                from docutils.core import publish_string
                html_code = publish_string(rst_code, writer_name='html')
                html_code = html_code.decode()

                # strip system message from html output
                open_tag = re.escape('<div class="first system-message">')
                close_tag = re.escape('</div>')
                pattern = '(' + open_tag + '.+?' + close_tag + ')'
                html_code = re.sub(pattern, '', html_code, flags=re.DOTALL)

                pkg_changelog_doc_path = os.path.join(
                    args.output_dir, 'changelogs', pkg.name)
                os.makedirs(pkg_changelog_doc_path)
                with open(os.path.join(
                        pkg_changelog_doc_path, 'changelog.html'), 'w') as h:
                    h.write(html_code)

    # create location files
    with Scope('SUBSECTION', 'create location files'):
        for pkg in pkgs.values():
            data = {
                'docs_url': '../../../api/%s/html' % pkg.name,
                'location': 'file://%s' % os.path.join(
                    args.output_dir, 'symbols', '%s.tag' % pkg.name),
                'package': pkg.name,
            }
            rosdoc_index.locations[pkg.name] = [data]
        # do not write these local locations

    # create rosdoc tag list files
    with Scope('SUBSECTION', 'create rosdoc tag list files'):
        for pkg in pkgs.values():
            dst = os.path.join(
                args.output_dir, 'rosdoc_tags', pkg.name, 'rosdoc_tags.yaml')
            print("Generating 'rosdoc_tags.yaml' file for package '%s'" %
                  pkg.name)

            dep_names = rosdoc_index.get_recursive_dependencies(pkg.name)
            # make sure that we don't pass our own tagfile to ourself
            # bad things happen when we do this
            assert pkg.name not in dep_names
            locations = []
            for dep_name in sorted(dep_names):
                if dep_name not in rosdoc_index.locations:
                    print("- skipping not existing location file of " +
                          "dependency '%s'" % dep_name)
                    continue
                dep_locations = rosdoc_index.locations[dep_name]
                if dep_locations:
                    for dep_location in dep_locations:
                        assert dep_location['package'] == dep_name
                        # update tag information to point to local location
                        location = copy.deepcopy(dep_location)
                        if not location['location'].startswith('file://'):
                            location['location'] = 'file://%s' % os.path.join(
                                args.rosdoc_index_dir, 'locations',
                                location['location'])
                        locations.append(location)

            dst_dir = os.path.dirname(dst)
            if not os.path.exists(dst_dir):
                os.makedirs(dst_dir)
            with open(dst, 'w') as h:
                yaml.dump(locations, h)

    # create manifest.yaml files from repository / package meta information
    # will be merged with the manifest.yaml file generated by rosdoc_lite later
    repository = dist_file.repositories[args.repository_name]
    with Scope('SUBSECTION', 'create manifest.yaml files'):
        for pkg in pkgs.values():

            data = {}

            #data['vcs'] = vcs_type
            #data['vcs_uri'] = vcs_uri
            #data['vcs_version'] = version

            data['repo_name'] = args.repository_name
            data['timestamp'] = time.time()

            data['depends'] = rosdoc_index.forward_deps.get(pkg.name, [])
            data['depends_on'] = rosdoc_index.reverse_deps.get(pkg.name, [])

            if pkg.name in rosdoc_index.metapackage_deps:
                data['metapackages'] = rosdoc_index.metapackage_deps[pkg.name]

            if pkg.name in package_names_with_changelogs:
                data['has_changelog_rst'] = True

            data['api_documentation'] = 'http://docs.ros.org/%s/api/%s' % \
                (args.rosdistro_name, pkg.name)

            pkg_status = None
            pkg_status_description = None
            # package level status information
            if pkg.name in repository.status_per_package:
                pkg_status_data = repository.status_per_package[pkg.name]
                pkg_status = pkg_status_data.get('status', None)
                pkg_status_description = pkg_status_data.get(
                    'status_description', None)
            # repository level status information
            if pkg_status is None:
                pkg_status = repository.status
            if pkg_status_description is None:
                pkg_status_description = repository.status_description
            if pkg_status is not None:
                data['maintainer_status'] = pkg_status
            if pkg_status_description is not None:
                data['maintainer_status_description'] = pkg_status_description

            # jenkins url + 'view' + view name + 'job' + job name
            # get_doc_view_name(
            #         args.rosdistro_name, args.doc_build_name)
            data['doc_job'] = get_doc_job_name(
                args.rosdistro_name, args.doc_build_name, args.repository_name,
                args.os_name, args.os_code_name, args.arch)

            # TODO
            # if pkg_release_jobs:
            #     data['release_jobs'] = pkg_release_jobs
            # if pkg_devel_jobs:
            #     data['devel_jobs'] = pkg_devel_jobs

            dst = os.path.join(
                args.output_dir, 'manifests', pkg.name, 'manifest.yaml')
            dst_dir = os.path.dirname(dst)
            if not os.path.exists(dst_dir):
                os.makedirs(dst_dir)
            with open(dst, 'w') as h:
                yaml.dump(data, h)

    # overwrite CMakeLists.txt files of each package
    with Scope(
        'SUBSECTION',
        'overwrite CMakeLists.txt files to only generate messages'
    ):
        for pkg_path, pkg in pkgs.items():
            abs_pkg_path = os.path.join(source_space, pkg_path)

            build_types = [
                e.content for e in pkg.exports if e.tagname == 'build_type']
            if build_types and build_types[0] == 'cmake':
                print("Ignore plain CMake package '%s' during build" %
                      pkg.name)
                catkin_ignore_file = os.path.join(
                    abs_pkg_path, 'CATKIN_IGNORE')
                with open(catkin_ignore_file, 'w'):
                    pass
            else:
                data = {
                    'package_name': pkg.name,
                }
                content = expand_template('doc/CMakeLists.txt.em', data)
                print("Generating 'CMakeLists.txt' for package '%s'" %
                      pkg.name)
                cmakelist_file = os.path.join(abs_pkg_path, 'CMakeLists.txt')
                with open(cmakelist_file, 'w') as h:
                    h.write(content)

    # initialize rosdep view
    context = initialize_resolver(
        args.rosdistro_name, args.os_name, args.os_code_name)

    apt_cache = Cache()

    debian_pkg_names = [
        'build-essential',
        'openssh-client',
        'python3',
        'python3-yaml',
        'rsync',
        # the following are required by rosdoc_lite
        'doxygen',
        'python-catkin-pkg',
        'python-epydoc',
        'python-kitchen',
        'python-rospkg',
        'python-sphinx',
        'python-yaml',
        'ros-%s-genmsg' % args.rosdistro_name,  # TODO remove
    ]
    if 'catkin' not in pkg_names:
        debian_pkg_names.append(
            get_debian_package_name(args.rosdistro_name, 'catkin'))
    print('Always install the following generic dependencies:')
    for debian_pkg_name in sorted(debian_pkg_names):
        print('  -', debian_pkg_name)

    debian_pkg_versions = {}

    # get build, run and doc dependencies and map them to binary packages
    depends = get_dependencies(
        pkgs.values(), 'build, run and doc', _get_build_run_doc_dependencies)
    debian_pkg_names_depends = resolve_names(depends, **context)
    debian_pkg_names_depends -= set(debian_pkg_names)
    debian_pkg_names += order_dependencies(debian_pkg_names_depends)
    debian_pkg_versions.update(
        get_binary_package_versions(apt_cache, debian_pkg_names))

    ordered_pkg_tuples = topological_order_packages(pkgs)

    # generate Dockerfile
    data = {
        'os_name': args.os_name,
        'os_code_name': args.os_code_name,
        'arch': args.arch,

        'distribution_repository_urls': args.distribution_repository_urls,
        'distribution_repository_keys': get_distribution_repository_keys(
            args.distribution_repository_urls,
            args.distribution_repository_key_files),

        'rosdistro_name': args.rosdistro_name,

        'uid': get_user_id(),

        'dependencies': debian_pkg_names,
        'dependency_versions': debian_pkg_versions,

        'ordered_pkg_tuples': ordered_pkg_tuples,
    }
    create_dockerfile(
        'doc/doc_task.Dockerfile.em', data, args.dockerfile_dir)


def create_stamp_files(pkg_names, output_dir):
    for pkg_name in sorted(pkg_names):
        dst = os.path.join(output_dir, pkg_name, 'stamp')
        os.makedirs(os.path.dirname(dst))
        with open(dst, 'w'):
            pass


def get_dependencies(pkgs, label, get_dependencies_callback):
    pkg_names = [pkg.name for pkg in pkgs]
    depend_names = set([])
    for pkg in pkgs:
        depend_names.update(
            [d.name for d in get_dependencies_callback(pkg)
             if d.name not in pkg_names])
    print('Identified the following %s dependencies ' % label +
          '(ignoring packages available from source):')
    for depend_name in sorted(depend_names):
        print('  -', depend_name)
    return depend_names


def _get_build_run_doc_dependencies(pkg):
    return pkg.build_depends + pkg.buildtool_depends + \
        pkg.build_export_depends + pkg.buildtool_export_depends + \
        pkg.exec_depends + pkg.doc_depends


def initialize_resolver(rosdistro_name, os_name, os_code_name):
    # resolve rosdep keys into binary package names
    ctx = create_default_installer_context()
    try:
        installer_key = ctx.get_default_os_installer_key(os_name)
    except KeyError:
        raise RuntimeError(
            "Could not determine the rosdep installer for '%s'" % os_name)
    installer = ctx.get_installer(installer_key)
    view = get_catkin_view(rosdistro_name, os_name, os_code_name, update=False)
    return {
        'os_name': os_name,
        'os_code_name': os_code_name,
        'installer': installer,
        'view': view,
    }


def resolve_names(rosdep_keys, os_name, os_code_name, view, installer):
    debian_pkg_names = set([])
    for rosdep_key in sorted(rosdep_keys):
        try:
            resolved_names = resolve_for_os(
                rosdep_key, view, installer, os_name, os_code_name)
        except KeyError:
            raise RuntimeError(
                "Could not resolve the rosdep key '%s'" % rosdep_key)
        debian_pkg_names.update(resolved_names)
    print('Resolved the dependencies to the following binary packages:')
    for debian_pkg_name in sorted(debian_pkg_names):
        print('  -', debian_pkg_name)
    return debian_pkg_names


def order_dependencies(binary_package_names):
    return sorted(binary_package_names)


if __name__ == '__main__':
    sys.exit(main())

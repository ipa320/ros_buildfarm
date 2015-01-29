import copy
import os
import subprocess
import time


def build_tagfile(
        apt_deps, tags_db, rosdoc_tagfile, current_package, ordered_deps,
        docspace, ros_distro, tags_location):
    #Get the relevant tags from the database
    tags = []

    for dep in apt_deps:
        if tags_db.has_tags(dep):
            #Make sure that we don't pass our own tagfile to ourself
            #bad things happen when we do this
            for tag in tags_db.get_tags(dep):
                if tag['package'] != current_package:
                    tag_copy = copy.deepcopy(tag)
                    #build the full path to the tagfiles
                    tag_copy['location'] = 'file://%s' % os.path.join(tags_location, 'tags', tag['location'])
                    tags.append(tag_copy)

    #Add tags built locally in dependency order
    for dep in ordered_deps:
        #we'll exit the loop when we reach ourself
        if dep == current_package:
            break

        key = 'ros-%s-%s' % (ros_distro, dep.replace('_', '-'))
        if tags_db.has_tags(key):
            tag = tags_db.get_tags(key)
            if len(tag) == 1:
                tag_copy = copy.deepcopy(tag[0])
                #build the full path to the tagfiles
                tag_copy['location'] = 'file://%s' % os.path.join(tags_location, 'tags', tag_copy['location'])
                tags.append(tag_copy)
        else:
            relative_tags_path = "doc/%s/tags/%s.tag" % (ros_distro, dep)
            if os.path.isfile(os.path.join(docspace, relative_tags_path)):
                tags.append({'docs_url': '../../%s/html' % dep,
                             'location': 'file://%s' % os.path.join(docspace, relative_tags_path),
                             'package': '%s' % dep})

    with open(rosdoc_tagfile, 'w+') as tags_file:
        import yaml
        yaml.dump(tags, tags_file)


class RosdocTagIndex(object):

    def __init__(self, rosdistro_name, rosdoc_tag_index_path):
        self.rosdistro_name = rosdistro_name
        self.path = rosdoc_tag_index_path

        self.tags = self.read_folder('tags')

        self.forward_deps = self.read_folder('deps')
        self.build_reverse_deps()

        self.metapackages = self.read_folder('metapackages')
        self.build_metapackage_index()

        self.rosinstall_hashes = self.read_folder('rosinstall_hashes')

    def has_rosinstall_hashes(self, rosinstall_name):
        return rosinstall_name in self.rosinstall_hashes

    def get_rosinstall_hashes(self, rosinstall_name, default=None):
        return self.rosinstall_hashes.get(rosinstall_name, default)

    def set_rosinstall_hashes(self, rosinstall_name, hashes):
        self.rosinstall_hashes[rosinstall_name] = hashes

    # turn a folder of files into a dict
    def read_folder(self, folder_name):
        import yaml
        folder_dict = {}
        path = os.path.join(self.path, self.rosdistro_name, folder_name)
        print('read_folder()', path)
        if os.path.exists(path):
            for key in os.listdir(path):
                print('-', key)
                with open(os.path.join(path, key), 'r') as f:
                    folder_dict[key] = yaml.load(f)
                    print(' ', folder_dict[key])
        return folder_dict

    # write a dict to a file with an entry per key
    def write_folder(self, folder_name, folder_dict):
        import yaml
        path = os.path.join(self.path, self.rosdistro_name, folder_name)

        # ensure that thedirectory exists
        if not os.path.isdir(path):
            os.makedirs(path)

        for key, values in folder_dict.items():
            with open(os.path.join(path, key), 'w') as f:
                yaml.safe_dump(values, f)

    def build_metapackage_index(self):
        self.metapackage_index = {}
        for package, deps in self.metapackages.items():
            for dep in deps:
                self.metapackage_index.setdefault(dep, []).append(package)

    def build_reverse_deps(self):
        self.reverse_deps = {}
        for package, deps in self.forward_deps.items():
            for dep in deps:
                self.reverse_deps.setdefault(dep, []).append(package)

    def get_recursive_dependencies(self, pkg_name):
        # since the dependencies available from the rosdoc_tag_index are not in
        # sync the algorithm must handle circular dependencies gracefully
        recursive_deps = set([])
        pkg_names = set([pkg_name])
        while len(pkg_names) > 0:
            name = pkg_names.pop()
            if name not in self.forward_deps:
                continue
            deps = set(self.forward_deps[name])
            assert name not in deps
            # consider only new dependencies
            deps -= recursive_deps
            # add to set to be traversed
            pkg_names |= deps
            # add to recursive dependencies
            recursive_deps |= deps
        return recursive_deps

    def has_tags(self, key):
        return key in self.tags

    def get_tags(self, key):
        return self.tags[key]

    def set_tags(self, key, tags):
        self.tags[key] = tags

    def has_reverse_deps(self, key):
        return key in self.reverse_deps

    def get_reverse_deps(self, key):
        return self.reverse_deps[key]

    def has_forward_deps(self, key):
        return key in self.forward_deps

    def get_forward_deps(self, key, default=None):
        if key not in self.forward_deps:
            return default
        return self.forward_deps[key]

    def set_forward_deps(self, key, deps):
        self.forward_deps[key] = deps
        self.build_reverse_deps()

    def has_metapackages(self, key):
        return key in self.metapackage_index

    def get_metapackages(self, key):
        return self.metapackage_index[key]

    def set_metapackage_deps(self, key, deps):
        self.metapackages[key] = deps
        if deps is None:
            del self.metapackages[key]
        self.build_metapackage_index()

    def write_data(self, includes=None):
        all_includes = ['deps', 'metapackages', 'rosinstall_hashes', 'tags']
        if includes is None:
            includes = all_includes

        for include in includes:
            assert include in all_includes

        if 'deps' in includes:
            self.write_folder('deps', self.forward_deps)
        if 'metapackages' in includes:
            self.write_folder('metapackages', self.metapackages)
        if 'rosinstall_hashes' in includes:
            self.write_folder('rosinstall_hashes', self.rosinstall_hashes)
        if 'tags' in includes:
            self.write_folder('tags', self.tags)

<project>
  <actions/>
  <description>Generated at @ESCAPE(now_str) from template '@ESCAPE(template_name)'</description>
@(SNIPPET(
    'log-rotator',
    days_to_keep=100,
    num_to_keep=100,
))@
  <keepDependencies>false</keepDependencies>
  <properties>
@[if github_url]@
@(SNIPPET(
    'property_github-project',
    project_url=github_url,
))@
@[end if]@
@[if job_priority is not None]@
@(SNIPPET(
    'property_job-priority',
    priority=job_priority,
))@
@[end if]@
@(SNIPPET(
    'property_parameters-definition',
    parameters=[
        {
            'type': 'boolean',
            'name': 'force',
            'description': 'Run documentation generation even if neither the source repository nor any of the tools have changes',
        },
    ],
))@
@(SNIPPET(
    'property_requeue-job',
))@
@(SNIPPET(
    'property_disk-usage',
))@
  </properties>
@(SNIPPET(
    'scm',
    repo_spec=doc_repo_spec,
    path='catkin_workspace/src/%s' % doc_repo_spec.name,
))@
  <assignedNode>buildslave</assignedNode>
  <canRoam>false</canRoam>
  <disabled>false</disabled>
  <blockBuildWhenDownstreamBuilding>false</blockBuildWhenDownstreamBuilding>
  <blockBuildWhenUpstreamBuilding>false</blockBuildWhenUpstreamBuilding>
  <triggers>
@(SNIPPET(
    'trigger_poll',
    spec='H 3 H/3 * *',
))@
  </triggers>
  <concurrentBuild>false</concurrentBuild>
  <builders>
@(SNIPPET(
    'builder_shell_docker-info',
))@
@(SNIPPET(
    'builder_shell',
    script='\n'.join([
        'echo "# BEGIN SECTION: Clone ros_buildfarm"',
        'rm -fr ros_buildfarm',
        'git clone %s%s ros_buildfarm' % ('-b %s ' % ros_buildfarm_repository.version if ros_buildfarm_repository.version else '', ros_buildfarm_repository.url),
        'git -C ros_buildfarm log -n 1',
        'echo "# END SECTION"',
        '',
        'echo "# BEGIN SECTION: rsync rosdoc_tag_index to slave"',
        'rm -fr rosdoc_tag_index',
        'rsync -e "ssh -o StrictHostKeyChecking=no" -qr --include="%s/***" jenkins-slave@repo:/var/repos/rosdoc_tag_index/ $WORKSPACE/rosdoc_tag_index' % rosdistro_name,
        'echo "# END SECTION"',
        '',
        'echo "# BEGIN SECTION: Clone rosdoc_lite"',
        'rm -fr rosdoc_lite',
        'git clone https://github.com/ros-infrastructure/rosdoc_lite.git rosdoc_lite',
        'git -C rosdoc_lite log -n 1',
        'echo "# END SECTION"',
    ]),
))@
@(SNIPPET(
    'builder_shell_key-files',
    script_generating_key_files=script_generating_key_files,
))@
@(SNIPPET(
    'builder_shell',
    script='\n'.join([
        'rm -fr $WORKSPACE/docker_generating_docker',
        'rm -fr $WORKSPACE/generated_documentation',
        'mkdir -p $WORKSPACE/docker_generating_docker',
        'mkdir -p $WORKSPACE/generated_documentation',
        '',
        '# monitor all subprocesses and enforce termination',
        'python3 -u $WORKSPACE/ros_buildfarm/scripts/subprocess_reaper.py $$ --cid-file $WORKSPACE/docker_generating_docker/docker.cid > $WORKSPACE/docker_generating_docker/subprocess_reaper.log 2>&1 &',
        '# sleep to give python time to startup',
        'sleep 1',
        '',
        '# generate Dockerfile, build and run it',
        '# generating the Dockerfiles for the actual doc task',
        'echo "# BEGIN SECTION: Generate Dockerfile - doc task"',
        'export TZ="%s"' % timezone,
        'export PYTHONPATH=$WORKSPACE/ros_buildfarm:$PYTHONPATH',
        'if [ "$force" = "true" ]; then FORCE_FLAG="--force"; fi',
        'python3 -u $WORKSPACE/ros_buildfarm/scripts/doc/run_doc_job.py' +
        ' --rosdistro-index-url ' + rosdistro_index_url +
        ' ' + rosdistro_name +
        ' ' + doc_build_name +
        ' ' + doc_repo_spec.name +
        ' ' + os_name +
        ' ' + os_code_name +
        ' ' + arch +
        ' ' + ' '.join(repository_args) +
        ' $FORCE_FLAG' +
        ' --dockerfile-dir $WORKSPACE/docker_generating_docker',
        'echo "# END SECTION"',
        '',
        'echo "# BEGIN SECTION: Build Dockerfile - generating doc task"',
        'cd $WORKSPACE/docker_generating_docker',
        'python3 -u $WORKSPACE/ros_buildfarm/scripts/misc/docker_pull_baseimage.py',
        'docker build -t doc_task_generation__%s_%s .' % (rosdistro_name, doc_repo_spec.name),
        'echo "# END SECTION"',
        '',
        'echo "# BEGIN SECTION: Run Dockerfile - generating doc task"',
        'rm -fr $WORKSPACE/docker_doc',
        'mkdir -p $WORKSPACE/docker_doc',
        'docker run' +
        ' --cidfile=$WORKSPACE/docker_generating_docker/docker.cid' +
        ' -e=HOME=/home/buildfarm' +
        ' -v $WORKSPACE/ros_buildfarm:/tmp/ros_buildfarm:ro' +
        ' -v $WORKSPACE/rosdoc_lite:/tmp/rosdoc_lite:ro' +
        ' -v $WORKSPACE/catkin_workspace:/tmp/catkin_workspace' +
        ' -v $WORKSPACE/generated_documentation:/tmp/generated_documentation' +
        ' -v $WORKSPACE/rosdoc_tag_index:/tmp/rosdoc_tag_index' +
        ' -v $WORKSPACE/docker_doc:/tmp/docker_doc' +
        ' doc_task_generation__%s_%s' % (rosdistro_name, doc_repo_spec.name),
        'echo "# END SECTION"',
    ]),
))@
@(SNIPPET(
    'builder_shell',
    script='\n'.join([
        'if [ ! -f "$WORKSPACE/docker_doc/Dockerfile" ]; then',
        '  exit 0',
        'fi',
        '',
        '# monitor all subprocesses and enforce termination',
        'python3 -u $WORKSPACE/ros_buildfarm/scripts/subprocess_reaper.py $$ --cid-file $WORKSPACE/docker_doc/docker.cid > $WORKSPACE/docker_doc/subprocess_reaper.log 2>&1 &',
        '# sleep to give python time to startup',
        'sleep 1',
        '',
        'echo "# BEGIN SECTION: Build Dockerfile - doc"',
        '# build and run build_and_install Dockerfile',
        'cd $WORKSPACE/docker_doc',
        'python3 -u $WORKSPACE/ros_buildfarm/scripts/misc/docker_pull_baseimage.py',
        'docker build -t doc__%s_%s .' % (rosdistro_name, doc_repo_spec.name),
        'echo "# END SECTION"',
        '',
        'echo "# BEGIN SECTION: Run Dockerfile - doc"',
        'docker run' +
        ' --cidfile=$WORKSPACE/docker_doc/docker.cid' +
        ' -v $WORKSPACE/ros_buildfarm:/tmp/ros_buildfarm:ro' +
        ' -v $WORKSPACE/rosdoc_lite:/tmp/rosdoc_lite:ro' +
        ' -v $WORKSPACE/catkin_workspace:/tmp/catkin_workspace' +
        ' -v $WORKSPACE/generated_documentation:/tmp/generated_documentation' +
        ' doc__%s_%s' % (rosdistro_name, doc_repo_spec.name),
        'echo "# END SECTION"',
    ]),
))@
@(SNIPPET(
    'builder_publish-over-ssh',
    config_name='docs',
    remote_directory=rosdistro_name,
    source_files=['generated_documentation/api/**/stamp', 'generated_documentation/changelogs/**/*.html', 'generated_documentation/tags/*.tag'],
    remove_prefix='generated_documentation',
))@
@(SNIPPET(
    'builder_shell',
    script='\n'.join([
        'if [ -d "$WORKSPACE/generated_documentation/api_rosdoc" ]; then',
        '  echo "# BEGIN SECTION: rsync API documentation"',
        '  cd $WORKSPACE/generated_documentation/api_rosdoc',
        '  for pkg_name in $(find . -maxdepth 1 -mindepth 1 -type d); do',
        '    rsync -e "ssh -o StrictHostKeyChecking=no" -qr --delete $pkg_name jenkins-slave@repo:/var/repos/docs/%s/api' % rosdistro_name,
        '  done',
        '  echo "# END SECTION"',
        'fi',
    ]),
))@
@(SNIPPET(
    'builder_shell',
    script='\n'.join([
        'echo "# BEGIN SECTION: rsync rosdoc_tag_index to server"',
        'rsync -e "ssh -o StrictHostKeyChecking=no" -qr $WORKSPACE/rosdoc_tag_index/%s jenkins-slave@repo:/var/repos/rosdoc_tag_index/' % rosdistro_name,
        'echo "# END SECTION"',
    ]),
))@
  </builders>
  <publishers>
@(SNIPPET(
    'publisher_groovy-postbuild_slave-low-disk-space',
))@
@[if notify_maintainers]@
@(SNIPPET(
    'publisher_groovy-postbuild_maintainer-notification',
))@
@[end if]@
@(SNIPPET(
    'publisher_mailer',
    recipients=notify_emails,
    dynamic_recipients=maintainer_emails,
    send_to_individuals=notify_committers,
))@
  </publishers>
  <buildWrappers>
@[if timeout_minutes is not None]@
@(SNIPPET(
    'build-wrapper_build-timeout',
    timeout_minutes=timeout_minutes,
))@
@[end if]@
@(SNIPPET(
    'build-wrapper_timestamper',
))@
@(SNIPPET(
    'build-wrapper_disk-check',
))@
@(SNIPPET(
    'build-wrapper_ssh-agent_credential-id',
))@
  </buildWrappers>
</project>

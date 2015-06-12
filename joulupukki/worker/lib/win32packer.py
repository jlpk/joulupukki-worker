import os
import re
import pecan
import timeit
import glob
import shutil
import yaml
import tarfile

from docker import errors
from datetime import datetime
from io import BytesIO

from joulupukki.worker.lib.packer import Packer

class Win32Packer(Packer):
    def parse_specdeb(self):
        # Get win infos
        self.logger.info("Find informations from spec file")

        """control_file_path = os.path.join(self.folder,
                                        'sources',
                                        self.config['root_folder'],
                                        self.config['win'],
                                        'control')"""
        self.logger.error(self.config)
        """changelog_file_path = os.path.join(self.folder,
                                           'sources',
                                           self.config['root_folder'],
                                           self.config['win'],
                                           'changelog')
        """

        # Prepare datas
        self.config['ccache'] = self.config.get('ccache', False)
        self.config['version'] = ''
        self.config['release'] = ''
        self.config['name'] = ''
        self.config['source'] = ''

        self.parseNsis()

        # Get source file
        self.config['source'] = self.config['name'] + "_" + self.config['version'] + ".orig.tar.gz"

        # Log informations
        self.logger.info("Name: %(name)s", self.config)
        self.logger.info("Source: %(source)s", self.config)
        self.logger.info("Version: %(version)s", self.config)
        self.logger.info("Release: %(release)s", self.config)

        try:
            self.commands = self.config["exe_commands"]
            self.dependencies = []
        except KeyError:
            self.logger.error("Malformed .packer.yml file")
            return False
        return True

    def docker_build(self):
        self.logger.info("Dockerfile preparation")
        dockerfile_path =  "%s/../../sources/docker/Dockerfile" % self.job.get_folder_path()
        f = open(dockerfile_path, 'r')
        dockerfile2 = f.read()

        f = BytesIO(dockerfile2.encode('utf-8'))
        self.logger.error(self.container_tag)
        # BUILD
        self.logger.info("Docker Image Building")
        output = self.cli.build(fileobj=f, rm=True, tag=self.container_tag, forcerm=True)
        # log output
        for i in output:
            dict_ = eval(i)
            if "stream" in dict_:
                self.logger.info(dict_["stream"].strip())
            else:
                if 'error' in dict_:
                    self.logger.info(dict_['errorDetail']['message'].strip())
                else:
                    self.logger.info(str(i))
        self.logger.info("Docker Image Built")
        return True

    def parseNsis(self):
        self.logger.info("Parsing Nsis file")
        nsisfile_path =  "%s/../../sources/%s" % (self.job.get_folder_path(), self.config["nsifile"])
        outFileRegex = re.compile("outFile \"([a-z\-]*\.exe)")
        with open(nsisfile_path) as f:
            content = f.read()
            result = outFileRegex.search(content)
            if result:
                self.config["package_name"] = result.groups()[0]
                self.logger.info("Package name : %s" % self.config["package_name"])
            #self.config["version"] = "%s.$s.%s" % (re.search("VERSIONMAJOR ([0-9])", content).groups()[0], re.search("VERSIONMINOR ([0-9])", content).groups()[0], re.search("VERSIONBUILD ([0-9])", content).groups()[0])
            #self.logger.info("Version : %s" % self.config["version"])
        return

    def docker_run(self):
        # PREPARE BUILD COMMAND
        docker_source_root_folder = os.path.join('upstream', self.config['root_folder'])

        commands = []
        volumes = ['/upstream']
        binds = {}

        # Handle build dependencies
        for depen in self.dependencies:
            commands.append("""yaourt -S %s""" % depen)

        # Prepare source
        commands.append("""sudo mkdir /sources""")
        commands.append("""rsync -rlptD --exclude '.git' /%s/%s""" % (docker_source_root_folder, self.config['name']))

        # Adding build commands
        for cmd in self.commands:
            commands.append("""%s""" % cmd)

        # Build
        if self.builder.build.snapshot:
            version = self.config['version']
            date = datetime.now().strftime("%Y%m%d%H%M%S")
            if self.builder.build.commit:
                commit = self.builder.build.commit[:7]
                self.config['release'] = date + "~git" + commit
            else:
                self.config['release'] = date

            new_version = "-".join((version, self.config['release']))

        # Finish command preparation
        command = "bash -c '%s'" % " && ".join(commands)
        self.logger.info("Build command: %s", command)

        # RUN
        self.logger.error(self.container_tag)
        self.logger.info("Win Build starting")
        start_time = timeit.default_timer()
        try:
            self.container = self.cli.create_container(self.container_tag, command=command, volumes=volumes, cpuset=pecan.conf.docker_cpuset)
        except Exception as exp:
            self.logger.error("Error launching docker container: %s", exp)
            return False
        local_source_folder = os.path.join(self.folder, "sources")
        binds[local_source_folder] = {"bind": "/upstream", "ro": True}
        toto = self.cli.start(self.container['Id'], binds=binds)

        for line in self.cli.attach(self.container['Id'], stdout=True, stderr=True, stream=True):
            self.logger.info(line.strip())
        # Stop container
        try:
            self.cli.stop(self.container['Id'])
        except errors.APIError as exp:
            self.logger.info("Container %s already stopped" % self.container['Id'])
        elapsed = timeit.default_timer() - start_time
        self.set_build_time(elapsed)
        self.logger.info("Win Build finished in %ds", elapsed)
        # Get exit code
        if self.cli.wait(self.container['Id']) != 0:
            return False
        else:
            return True


    def get_output(self):
        # Get exe from the container
        tar_raw = self.cli.copy(self.container['Id'], "/output")
        exe_tar = tarfile.open(fileobj=BytesIO(tar_raw.read()))

        try:
            # move files to folder output
            exe_tar.extractall(self.job_tmp_folder)
        except:
            exe_tar.close()
            return False
        exe_tar.close()

        shutil.move(self.job_tmp_folder+"/output", self.folder_output+"/"+self.config["package_name"])

        self.logger.info("Win files deposed in %s" % self.folder_output)
        return True

import os
import subprocess
import pecan
import yaml
import shutil

from joulupukki.common.logger import get_logger_job
from joulupukki.common.datamodel.job import Job


class OsxPacker(object):
    def __init__(self, builder, config):
        self.config = config
        self.builder = builder
        self.distro = "osx"

        self.source_url = builder.source_url
        self.source_type = builder.source_type
        self.branch = builder.build.branch
        self.folder = builder.folder

        job_data = {
            'distro': self.distro,
            'username': self.builder.build.username,
            'project_name': self.builder.build.project_name,
            'build_id': self.builder.build.id_,
        }
        self.job = Job(job_data)
        self.job.create()
        self.folder_output = self.job.get_folder_output()

        self.job_tmp_folder = self.job.get_folder_tmp()

        if not os.path.exists(self.folder_output):
            os.makedirs(self.folder_output)
        if not os.path.exists(self.job_tmp_folder):
            os.makedirs(self.job_tmp_folder)

        self.logger = get_logger_job(self.job)

    def set_status(self, status):
        self.job.set_status(status)

    def set_build_time(self, build_time):
        self.job.set_build_time(build_time)

    def run(self):
        steps = (
            ('cloning', self.clone),
            ('reading_conf', self.reading_conf),
            ('setup', self.setup),
            ('compiling', self.compile_),
            ('transfering', self.transfert_output),
        )
        for step_name, step_function in steps:
            self.set_status(step_name)
            if step_function() is not True:
                self.logger.debug("Task failed during step: %s", step_name)
                self.set_status('failed')
                return False
            # Save package name in build.cfg
            if (self.config.get('name') is not None and
                    self.builder.build.package_name is None):
                self.builder.build.package_name = self.config.get('name')
                self.builder.build._save()
        self.set_status('succeeded')
        return True

    def clone(self):
        self.logger.info("Cloning main repo")
        self.logger.info(self.job.get_folder_tmp())
        cmds = [
            "cd %s" % self.job.get_folder_tmp(),
            "git clone -b %s %s source/" % (self.branch, self.source_url),
        ]
        command = " && "
        command = command.join(cmds)

        return self.exec_cmd(command)

    def reading_conf(self):
        self.logger.info("Reading conf from main repo")
        conf_file = "%s/source/.packer.yml" % self.job.get_folder_tmp()
        try:
            stream = open(conf_file, "r")
        except IOError:
            self.logger.error(".packer.yml not present")
            return False
        docs = yaml.load_all(stream)
        osx_conf = {}
        for doc in docs:
            for key, value in doc.items():
                osx_conf[key] = value

        try:
            self.dependencies = osx_conf['osx']['brew_deps']
            self.commands = osx_conf['osx']['commands']
        except KeyError:
            self.logger.error("Malformed .packer.yml file")
            return False
        return True

    def setup(self):
        # Installing dependencies
        for depen in self.dependencies:
            cmd_list = ["brew", "install"]
            cmd_list.extend(depen.split(" "))
            self.logger.info("Installing dependency: %s" % depen)
            process = subprocess.Popen(
                cmd_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = process.communicate()
            self.logger.debug(stdout)
            self.logger.info(stderr)
            if process.returncode:
                self.logger.error("Error in setup: %d" % process.returncode)
                return False
        return True

    def compile_(self):
        self.logger.info("Start compiling")
        # Compiling ring-daemon
        cd_command = ["cd %s" % self.job.get_folder_tmp()]
        self.commands = cd_command + self.commands
        long_command = " && "
        long_command = long_command.join(self.commands)
        long_command = long_command % {
            "prefix_path": pecan.conf.workspace_path
        }

        self.logger.info("Compiling")
        process = subprocess.Popen(
            long_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True
        )
        stdout, stderr = process.communicate()
        self.logger.debug(stdout)
        self.logger.info(stderr)
        if process.returncode:
            self.logger.error("Error in setup: %d" % process.returncode)
            return False
        return True

    def transfert_output(self):
        self.logger.info("Start package transfert")

        try:
            origin = (self.job.get_folder_tmp() +
                      "/libringclient/ring-client-macosx/build/Ring.dmg")
            destination = (self.builder.build.get_folder_path() +
                           "/output/osx/Ring.dmg")
            os.rename(origin, destination)
        except Exception:
            self.logger.error("Can't move .dmg file")
            return False

        host = pecan.conf.origin_host
        user = pecan.conf.origin_user
        key = pecan.conf.origin_key
        # TODO: Correct source and dest (package_dir and path), output/*
        # TODO: Add the transfert of jobs/*
        path = self.builder.origin_build_path + "/output/"
        package_dir = self.builder.build.get_folder_path() + "/output/*"
        transfert_command = "scp -r -i %s %s %s@%s:%s" % (
            key,
            package_dir,
            user,
            host,
            path
        )

        if not self.exec_cmd(transfert_command):
            return False

        try:
            shutil.rmtree(self.job.get_folder_path() + "/tmp")
        except Exception as e:
            self.logger.error("Couldn't remove tmp job files: " + e)

        path = self.builder.origin_build_path + "/jobs/"
        package_dir = (self.job.get_folder_path() + "/../" +
                       str(self.job.id_) + "/")
        transfert_command = "scp -r -i %s %s %s@%s:%s" % (
            key,
            package_dir,
            user,
            host,
            path
        )
        return self.exec_cmd(transfert_command)

    def clean(self):
        try:
            shutil.rmtree(self.builder.build.get_folder_path())
        except Exception:
            self.logger.error("Could not remove temps files: %s" % (
                self.builder.build.get_folder_path()
            ))
            return False
        return True

    def exec_cmd(self, cmds):
        process = subprocess.Popen(
            cmds,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True
        )
        stdout, stderr = process.communicate()
        self.logger.debug(stdout)
        self.logger.info(stderr)
        if process.returncode:
            self.logger.error("Error in setup: %d" % process.returncode)
            return False
        return True

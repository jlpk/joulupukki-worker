import os
import subprocess
import pecan
import shutil

from joulupukki.common.logger import get_logger_job
from joulupukki.common.datamodel.job import Job


class OsxPacker(object):
    def __init__(self, builder, config, job_id):
        self.config = config
        self.builder = builder
        self.distro = "osx"

        self.source_url = builder.source_url
        self.source_type = builder.source_type
        self.branch = builder.build.branch
        self.folder = builder.folder

        self.job = Job.fetch(self.builder.build, job_id)
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
#            ('transfering', self.transfert_output),
        )
        for step_name, step_function in steps:
            self.set_status(step_name)
            if step_function() is not True:
                self.logger.debug("Task failed during step: %s", step_name)
                # Set status
                self.set_status('failed')
                # Transfert output to central joulupukki
                self.transfert_output()
                return False
            # Save package name in build.cfg
            if (self.config['info']['name'] is not None and
                    self.builder.build.package_name is None):
                self.builder.build.package_name = self.config['info']['name']
                self.builder.build._save()
        # Transfert output to central joulupukki
        self.transfert_output()
        # Set status
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
        self.logger.info("Checking conf")
        try:
            self.dependencies = self.config['brew_deps']
            self.commands = self.config['commands']
            self.transfer_files = self.config['transfer']['files']
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

	# move dmg
        try:
            for f in transfert_files:
                origin = (self.job.get_folder_tmp() + f)
                destination = (self.builder.build.get_folder_path() +
                               "/output/" +
                               f.split('/')[-1])
                os.rename(origin, destination)
        except Exception:
            self.logger.error("Can't move output file(s)")
            #return False

        # Delete useless files
        try:
            shutil.rmtree(self.job.get_folder_path() + "/tmp")
        except Exception as e:
            self.logger.error("Couldn't remove tmp job files: " + e)

        host = pecan.conf.origin_host
        user = pecan.conf.origin_user
        key = pecan.conf.origin_key
        # TODO: Correct source and dest (package_dir and path), output/*
        # TODO: Add the transfert of jobs/*
        path = self.builder.origin_build_path
        package_dir = self.builder.build.get_folder_path() + "/*"
        # transfert_command = "scp -r -i %s %s %s@%s:%s" % (
        transfert_command = 'rsync -az -e "ssh -i %s" %s %s@%s:%s --exclude jobs/*/tmp' % (
            key,
            package_dir,
            user,
            host,
            path
        )
        self.logger.info(transfert_command)
        command_res = self.exec_cmd(transfert_command)
        self.logger.info(command_res)
        return command_res

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

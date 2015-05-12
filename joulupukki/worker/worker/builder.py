from threading import Thread
from docker import Client

import pecan


class Builder(Thread, ):
    def __init__(self, distro_name, build_conf, root_folder, logger, build,
                 origin_build_path, job_id):
        self.source_url = build.source_url
        self.source_type = build.source_type

        self.distro_name = distro_name
        self.build_conf = build_conf
        self.root_folder = root_folder
        self.logger = logger
        self.build = build
        self.job_id = job_id
        self.origin_build_path = origin_build_path

        try:
            self.cli = Client(base_url='unix://var/run/docker.sock',
                              version=pecan.conf.docker_version)
        except:
            pass

        self.folder = build.get_folder_path()

    def run(self):
        pass

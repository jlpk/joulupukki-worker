import os
import re
import pecan
import timeit
import glob
import shutil
import yaml

from docker import errors
from datetime import datetime
from io import BytesIO

from joulupukki.worker.lib.packer import Packer


class Win32Packer(Packer):
    def parse_specdeb(self):
        # Get win infos
        # self.container_tag += "-win_32"
        self.logger.info("Find informations from spec file")

        """control_file_path = os.path.join(self.folder,
                                         'sources',
                                         self.config['root_folder'],
                                         self.config['debian'],
                                         'control')"""
        self.logger.error(self.config)
        """changelog_file_path = os.path.join(self.folder,
                                           'sources',
                                           self.config['root_folder'],
                                           self.config['win'],
                                           'changelog')
        """
        # Prepare datas
        # self.config['deps'] = self.config.get('deps', [])
        # self.config['deps_pip'] = self.config.get('deps_pip', [])
        self.config['ccache'] = self.config.get('ccache', False)
        self.config['version'] = ''
        self.config['release'] = ''
        self.config['name'] = ''
        self.config['source'] = ''

        # deb_info = load_control_file(control_file_path)
        # self.config['name'] = deb_info.get("Source")
        # self.config['deps'] += parse_depends(deb_info.get('Build-Depends')).names
        
        version_release_pattern = re.compile("[^ ]* \(([^ ]*)\) .*")
        # Get source file
        self.config['source'] = self.config['name'] + "_" + self.config['version'] + ".orig.tar.gz"

        # Log informations
        self.logger.info("Name: %(name)s", self.config)
        self.logger.info("Source: %(source)s", self.config)
        self.logger.info("Version: %(version)s", self.config)
        self.logger.info("Release: %(release)s", self.config)
        conf_file = pecan.conf.workspace_path + "/win_conf.yml"
        # conf_file = "%s/source/.packer.yml" % self.job.get_folder_tmp()
        try:
            stream = open(conf_file, "r")
        except IOError:
            self.logger.error(".packer.yml not present")
            return False
        docs = yaml.load_all(stream)
        win_conf = {}
        for doc in docs:
            for key, value in doc.items():
                win_conf[key] = value

        try:
            if 'exe_deps' in win_conf['win32']:
                self.dependencies = win_conf['win32']['exe_deps']
            else:
                self.dependencies = []
            self.commands = win_conf['win32']['exe_commands']
        except KeyError:
            self.logger.error("Malformed .packer.yml file")
            return False
        return True

    def docker_build(self):
        self.logger.info("Dockerfile preparation")
        f = open(pecan.conf.workspace_path + "/Dockerfile", 'r')
        dockerfile2 = f.read()
        # DOCKER FILE TEMPLATE
        dockerfile = '''
        FROM nfnty/arch-mini
        RUN pacman -Syu --noconfirm
        RUN echo "[archlinuxfr]" >> /etc/pacman.conf
        RUN echo "SigLevel = Never" >> /etc/pacman.conf
        RUN echo "Server = http://repo.archlinux.fr/\$arch" >> /etc/pacman.conf
        RUN cat /etc/pacman.conf
        RUN useradd joulupukki -m
        RUN mkdir /opt/gettext
        RUN chown joulupukki /opt/gettext
        RUN pacman -Syu yaourt base base-devel wget --noconfirm
        RUN echo "joulupukki ALL= NOPASSWD: ALL" >> /etc/sudoers
        '''

        # Get keys
        keys = "D605848ED7E69871 9766E084FB0F43D8 4DE8FF2A63C7CC90 D9C4D26D0E604491 BB5869F064EA74AB"
        dockerfile += '''
        USER joulupukki
        RUN gpg --recv-keys {0} || gpg --recv-keys {0} || gpg --recv-keys {0}
        '''.format(keys)

        # mingw-w64-gettext need to be installed manually because the package is broken
        # Get mingw-w64-gettext dependencies
        # RUN yaourt -S mingw-w64-libiconv 
        dockerfile += '''
        RUN yaourt -S mingw-w64-termcap mingw-w64-libunistring --noconfirm
        '''
        # We get the package and rebuild it because there's misplaced files
        # We need to makepkg 3 time: 2 first is to generate the needed file and move them, third is to actually build it.
        dockerfile += '''
        RUN ls -al /opt/gettext
        WORKDIR /opt/gettext
        RUN ls -al
        RUN wget https://aur.archlinux.org/packages/mi/mingw-w64-gettext/mingw-w64-gettext.tar.gz 
        RUN tar -xzvf mingw-w64-gettext.tar.gz 
        WORKDIR mingw-w64-gettext
        RUN makepkg -Acs || true
        RUN cp src/gettext-0.19.4/build-i686-w64-mingw32/gettext-runtime/intl/libintl.h src/gettext-0.19.4/build-i686-w64-mingw32/gettext-tools/intl/
        RUN makepkg -Acs || true
        RUN cp src/gettext-0.19.4/build-x86_64-w64-mingw32/gettext-runtime/intl/libintl.h src/gettext-0.19.4/build-x86_64-w64-mingw32/gettext-tools/intl/
        RUN makepkg -Acs
        RUN sudo pacman -U mingw-w64-gettext-0.19.4-2-any.pkg.tar.xz --noconfirm
        '''

        # Installing mingw-w64-qt5-base-opengl because mingw-w64-qt5-base is broken
        dockerfile += '''
        RUN yaourt -S mingw-w64-qt5-base-opengl mingw-w64-qt5-svg --noconfirm
        RUN yaourt -S rsync git yasm --noconfirm
        '''

        f = BytesIO(dockerfile.encode('utf-8'))
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

    def parse_spedeb(self):
        self.logger.info("Reading win conf from main repo.")
        conf_file = pecan.conf.workspace_path + "/win_conf.yml"
        # conf_file = "%s/source/.packer.yml" % self.job.get_folder_tmp()
        try:
            stream = open(conf_file, "r")
        except IOError:
            self.logger.error(".packer.yml not present")
            return False
        docs = yaml.load_all(stream)
        win_conf = {}
        for doc in docs:
            for key, value in doc.items():
                win_conf[key] = value

        try:
            if 'exe_deps' in win_conf['win']:
                self.dependencies = win_conf['win']['exe_deps']
            else:
                self.dependencies = []
            self.commands = win_conf['win']['exe_commands']
        except KeyError:
            self.logger.error("Malformed .packer.yml file")
            return False
        return True
        

    def docker_run(self):
        # PREPARE BUILD COMMAND
        docker_source_root_folder = os.path.join('upstream', self.config['root_folder'])

        commands = []
        # commands.append("""cat /etc/sudoers""")
        # commands.append("""su joulupukki""")
        # commands.append("""yaourt -Syu""")
        volumes = ['/upstream']
        binds = {}

        # Handle ccache
        """if pecan.conf.ccache_path is not None and self.config.get('ccache', False):
            self.logger.info("CCACHE is enabled")
            ccache_path = os.path.join(pecan.conf.ccache_path,
                                       self.builder.build.username,
                                       self.config['name'],
                                       self.config['distro'].replace(":", "_"))
            if not os.path.exists(ccache_path):
                try:
                    os.makedirs(ccache_path)
                except Exception as exp:
                    self.logger.error("CCACHE folder creation error: %s", exp)
                    return False
            volumes.append('/ccache')
            binds[ccache_path] = {"bind": "/ccache"}"""
        #    commands.append("""apt-get install -y ccache""")
        #    commands.append("""export PATH=/usr/lib/ccache:$PATH""")
        #    commands.append("""export CCACHE_DIR=/ccache""")
        
        # Handle build dependencies
        # if self.config['deps']:
        #    commands.append("""apt-get install -y %s""" % " ".join(self.config['deps']))
        # Handle python build dependencies
        #if self.config['deps_pip']:
        #    commands.append("""apt-get install -y python-setuptools""")
        #    commands.append("""easy_install %s""" % " ".join(self.config['deps_pip']))
        
        # Handle build dependencies
        for depen in self.dependencies:
            commands.append("""yaourt -S %s""" % depen)

        # Prepare source
        commands.append("""sudo mkdir /sources""")
        commands.append("""rsync -rlptD --exclude '.git' /%s/%s""" % (docker_source_root_folder, self.config['name']))
        # commands.append("""cd contrib""")

        # Adding build commands
        for cmd in self.commands:
            commands.append("""%s""" % cmd)

        # Build
        commands.append("""cd /sources/%s """ % self.config['name'])
        if self.builder.build.snapshot:
            version = self.config['version']
            date = datetime.now().strftime("%Y%m%d%H%M%S")
            if self.builder.build.commit:
                commit = self.builder.build.commit[:7]
                self.config['release'] = date + "~git" + commit
            else:
                self.config['release'] = date

            new_version = "-".join((version, self.config['release']))
        
        commands.append("""mkdir /output""")
        commands.append("""mv * /output""")
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
            self.logger.info("Contairner %s already stopped" % self.container['Id'])
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
        exe_raw = self.cli.copy(self.container['Id'], "/output")
        exe_tar = tarfile.open(fileobj=BytesIO(exe_raw.read()))
        try:
            # move files to folder output
            exe_tar.extractall(self.job_tmp_folder)
        except:
            exe_tar.close()
            return False
        exe_tar.close()
        # move files to folder output
        for file_ in glob.glob(os.path.join(self.job_tmp_folder, "*/*")):
            shutil.move(file_, self.folder_output)

        self.logger.info("Win files deposed in output folder")
        return True

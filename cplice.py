import argparse
from dataclasses import dataclass
import functools
import hashlib
from http import cookiejar
import json
from pathlib import Path

import requests


parser = argparse.ArgumentParser()
parser.add_argument('basecontainer', help='Base software container to use for the new container')
parser.add_argument('datacontainer', help='Container with the model data to use for the new container')
parser.add_argument('newcontainer', help='Name of the new container')
parser.add_argument('--insecure', '-k', action='store_true', help='Allow insecure connections to the registry')
args = parser.parse_args()


class BlockAll(cookiejar.CookiePolicy):
    return_ok = set_ok = domain_return_ok = path_return_ok = lambda self, *args, **kwargs: False
    netscape = True
    rfc2965 = hide_cookie2 = False


class DockerConfig:
    def __init__(self):
        with open(Path.home() / '.docker' / 'config.json') as f:
            self.config = json.load(f)
    
    def get_auth(self, host):
        return self.config['auths'][host]['auth']

config = DockerConfig()


class Registry:
    def __init__(self, host, verify=True):
        self.host = host
        self.session = requests.Session()
        self.session.verify = verify
        self.session.cookies.set_policy(BlockAll())
        self.token = None
    
    def get_auth(self):
        return config.get_auth(self.host)
    
    def __headers(self, additional={}):
        base = {'Authorization': f'Basic {config.get_auth(self.host)}'}
        base.update(additional)
        return base
    
    @functools.cache
    def get_manifest(self, image, tag):
        url = f'https://{self.host}/v2/{image}/manifests/{tag}'
        response = self.session.get(url, headers=self.__headers())
        return response.json()
    
    @functools.cache
    def get_blob(self, image, digest):
        url = f'https://{self.host}/v2/{image}/blobs/{digest}'
        response = self.session.get(url, headers=self.__headers())
        return response.content
    
    @functools.cache
    def get_config(self, image, tag):
        manifest = self.get_manifest(image, tag)
        config_digest = manifest['config']['digest']
        data = self.get_blob(image, config_digest)
        return json.loads(data)
    
    def head_blob(self, image, digest):
        url = f'https://{self.host}/v2/{image}/blobs/{digest}'
        response = self.session.head(url, headers=self.__headers())
        return response.status_code, response.headers
    
    def store_blob(self, image, data=None, jsondata=None):
        if jsondata:
            data = bytes(json.dumps(jsondata), 'utf-8')
        digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
        url = f'https://{self.host}/v2/{image}/blobs/uploads/'
        response = self.session.post(url,
                                     headers=self.__headers({'Content-Type': 'application/octet-stream'}),
                                     data=data,
                                     params={'digest': digest}
                                     )
        try:
            response.raise_for_status()
            return digest
        except Exception as e:
            print(response.text)
            raise e
    
    def store_manifest(self, image, manifest):
        url = f'https://{self.host}/v2/{image}/manifests/latest'
        data = json.dumps(manifest)
        response = self.session.put(url,
                                    headers=self.__headers({'Content-Type': 'application/vnd.oci.image.manifest.v1+json'}),
                                    data=data,
                                    )
        try:
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(response.text)
            raise e
    

class Registries:
    def __init__(self):
        self.registries = {}
    
    def get(self, host, verify=True):
        if host not in self.registries:
            self.registries[host] = Registry(host, verify=verify)
        return self.registries[host]

registries = Registries()

class ContainerReference:
    host: str
    path: str
    tag: str

    def __init__(self, image, verify=True):
        self.host, pathtag = image.split('/', 1)
        self.path, self.tag = pathtag.split(':', 1)
        self.registry = registries.get(self.host, verify=verify)

    def manifest(self):
        return self.registry.get_manifest(self.path, self.tag)
    
    @functools.cache
    def config(self):
        return self.registry.get_config(self.path, self.tag)
    
    def touch_layers(self, layers=[]):
        for layer in layers:
            print(self.registry.head_blob(self.path, layer))
    
    def store_config(self, config):
        return self.registry.store_blob(self.path, jsondata=config)
    
    def store_manifest(self, manifest):
        return self.registry.store_manifest(self.path, manifest)


class ContainerSplice:
    def __init__(self, basecontainer, datacontainer, newcontainer, verify=True):
        self.base = ContainerReference(basecontainer, verify=verify)
        self.data = ContainerReference(datacontainer, verify=verify)
        self.new = ContainerReference(newcontainer, verify=verify)



cplice = ContainerSplice(
    args.basecontainer,
    args.datacontainer,
    args.newcontainer,
    verify=not args.insecure
)


def printy(title, s):
    print(json.dumps(s, indent=2))

basem = cplice.base.manifest()
basec = cplice.base.config()
printy("Base Manifest", basem)
printy("Base Config", basec)

datam = cplice.data.manifest()
datac = cplice.data.config()
printy("Data Manifest", datam)
printy("Data Config", datac)

basem['layers'] = basem['layers'] + datam['layers']
basec['history'] = basec['history'] + datac['history']
basec['rootfs']['diff_ids'] = basec['rootfs']['diff_ids'] + datac['rootfs']['diff_ids']
basem['mediaType'] = 'application/vnd.oci.image.manifest.v1+json'

digest = cplice.new.store_config(basec)
printy("New config digest", digest)

basem['config']['digest'] = digest
printy("New manifest", basem)
printy("New config", basec)
printy(cplice.new.store_manifest(basem))


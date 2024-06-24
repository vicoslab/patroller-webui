import os, json
import urllib.request, base64

__DEFAULT_CONFIG_PATH = "/etc/patroller/web-ui.json"
__DEFAULT_DATABASE_PATH = "/code/occupancy_data.parquet"

def _load_config( cfg_path):
    if os.path.exists(cfg_path):
        with open(cfg_path,'r') as f:
            cfg = json.load(f)
    else:
        cfg = dict(servers=[])
    
    return cfg

class Patroller:
    def __init__(self, cfg_path):
        self.cfg = _load_config(cfg_path)
    
    def __len__(self):
        return len(self.cfg['servers'])
    
    def __iter__(self):
        cfg = self.cfg 

        gpu_servers = cfg['servers']

        url_auth = None
        if 'http_auth_user' in self.cfg and 'http_auth_pass' in cfg:
            url_auth = base64.b64encode(('%s:%s' % (cfg['http_auth_user'],
                                                    cfg['http_auth_pass'])).encode('ascii'))

        for server_cfg in gpu_servers:
            server_name = server_cfg['name']
            server_url = server_cfg['url']
            
            try:
                request = urllib.request.Request(server_url)
                
                if 'http_auth_user' in server_cfg and 'http_auth_pass' in server_cfg:
                    url_auth = base64.b64encode(('%s:%s' % (server_cfg['http_auth_user'],
                                                            server_cfg['http_auth_pass'])).encode('ascii'))

                if url_auth is not None and not server_cfg.get('disable_auth'):
                    request.add_header("Authorization", "Basic %s" % url_auth.decode("ascii"))

                with urllib.request.urlopen(request, timeout=5) as url:
                    gpu_data = json.loads(url.read().decode())

                yield dict(name=server_name,url=server_url, data=gpu_data)
                
            except Exception as ex:
                import traceback
                print("Unable to retrieve status from '%s'" % server_url)
                traceback.print_exception(type(ex), ex, ex.__traceback__)
                
                yield dict(name=server_name,url=server_url, data=None)


        

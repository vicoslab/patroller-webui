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

def read_json_webpage(server_url, user=None, password=None, timeout=5):
    request = urllib.request.Request(server_url)
    
    if user and password:
        url_auth = base64.b64encode(('%s:%s' % (user, password)).encode('ascii'))
        
        request.add_header("Authorization", "Basic %s" % url_auth.decode("ascii"))

    with urllib.request.urlopen(request, timeout=timeout) as url:
        return json.loads(url.read().decode())

class Patroller:
    __STATUS_PAGE = "/status"
    __DEVICES_PAGE = "/devices"
    __REQUEST_PAGE = "/request"
    __WAIT_PAGE = "/wait"

    def __init__(self, cfg_path):
        self.cfg = _load_config(cfg_path)
    
    def __len__(self):
        return len(self.cfg['servers'])
    
    def list_servers(self):
        return [s['name'] for s in self.cfg['servers']]

    def __iter__(self):
        cfg = self.cfg 

        gpu_servers = cfg['servers']

        
        user, password = None, None
        if 'http_auth_user' in self.cfg and 'http_auth_pass' in cfg:
            user, password = cfg['http_auth_user'], cfg['http_auth_pass']

        for server_cfg in gpu_servers:
            server_name = server_cfg['name']
            server_url_status = server_cfg['url'] + self.__STATUS_PAGE
            server_url_device = server_cfg['url'] + self.__DEVICES_PAGE
            try:

                server_user, server_password = user, password
                if 'http_auth_user' in server_cfg and 'http_auth_pass' in server_cfg:
                    server_user, server_password = server_cfg['http_auth_user'], server_cfg['http_auth_pass']
                if server_cfg.get('disable_auth'):
                    server_user, server_password = None, None

                gpu_data = read_json_webpage(server_url_status, server_user, server_password)
                gpu_details = read_json_webpage(server_url_device, server_user, server_password)

                yield dict(name=server_name,url=server_url_status, data=gpu_data, devs=gpu_details)
                
            except Exception as ex:
                import traceback
                print("Unable to retrieve status from '%s'" % server_url_status)
                traceback.print_exception(type(ex), ex, ex.__traceback__)
                
                yield dict(name=server_name,url=server_url_status, data=None)


import pandas as pd

class PatrollerHistory:
    def __init__(self, cfg_path, db_path):
        self.patroller = Patroller(cfg_path=cfg_path)
        
        self.data = pd.read_parquet(db_path)

    def list_servers(self):
        return self.patroller.list_servers()

    def get_history(self):
        return self.data


    def find_server_gpus(self, servers=None):

        df = self.data

        # retrieve all server GPUs    
        server_gpus = dict()
        server_offline = []

        for server_cfg in self.patroller:
            server_name = server_cfg['name']

            # skip if not requested this one
            if servers is not None and server_name not in servers:
                continue

            if server_cfg['data'] is not None:
                # get data from server
                server_gpus[server_name] = [gpu_id for gpu_id,_ in server_cfg['data'].items()] 
            else:            
                # server is unavailable so try to get gpus from histroy
                server_offline.append(server_name)

                # get all gpus for this server
                missing_server_gpus = df[df['server'] == server_name].reset_index()
                missing_server_gpus = missing_server_gpus[['gpu','gpu_index']]

                # if there are multiple gpu with the same gpu_index, then use only the last one (for instance if GPU has been replaced but history contains older entries)
                missing_server_gpus = missing_server_gpus.drop_duplicates(subset='gpu_index', keep='last')

                gpu_index_to_id = dict(zip(missing_server_gpus['gpu_index'],missing_server_gpus['gpu']))

                server_gpus[server_name] = [gpu_index_to_id[i] if i in gpu_index_to_id else 'unknown' for i in range(missing_server_gpus['gpu_index'].max()+1)]

        return server_gpus, server_offline

        
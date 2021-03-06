import socket
import time

import requests
from paramiko import SSHException
from retrying import retry


# ref: https://www.vultr.com/api/
def vultr_call(method="GET", api_name=None, api_key=None, **kwargs):
    url = "https://api.vultr.com/v1/" + api_name
    res = requests.request(method, url, headers={"API-Key": api_key},
                           params=kwargs if method == "GET" else None,
                           data=kwargs if method == "POST" else None)
    if res.status_code == 200:
        if res.text.strip() == "":
            return ""
        return res.json()
    else:
        raise requests.HTTPError(res.text)


with open("apikey.txt") as f:
    api_key = f.read()
    api_key = api_key.strip()


def get_now_ms():
    return time.perf_counter() * 1000


def port_check(host, port):
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sk.settimeout(2)
    try:
        sk.connect((host, port))
        return True
    except Exception:
        pass
    sk.close()
    return False


@retry(wait_fixed=10 * 1000, stop_max_delay=120 * 1000, stop_max_attempt_number=120,
       retry_on_result=lambda v: v[1] == "not supported",
       )
def get_new_server_ip_and_password(new_server_sub_id):
    print("trying get_new_server_ip_and_password")
    vps_list = vultr_call("GET", "server/list", api_key=api_key)
    if len(vps_list) == 1:
        vps = vps_list[str(new_server_sub_id)]
        print(vps)
        return vps["main_ip"], vps["default_password"]

    else:
        print("VPS状态可能存在问题！！！")
        for key in vps_list:
            print(vps_list[key])
        raise RuntimeError


def retry_on_timeout_or_ssh_error(e):
    print(e)
    return isinstance(e, socket.timeout) or isinstance(e, SSHException)


server_starting_time = None


@retry(wait_fixed=2 * 1000, stop_max_delay=120 * 1000, stop_max_attempt_number=120,
       retry_on_exception=retry_on_timeout_or_ssh_error)
def ssh_install_and_run_ss(host, port, user, password, ss_port, ss_password):
    print("ssh root@" + ip)
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ssh.connect(hostname=host, port=port, username=user, password=password, timeout=5,
                allow_agent=False, look_for_keys=False)
    elapsed_ms = get_now_ms() - server_starting_time
    print("time elapsed %fs" % (elapsed_ms / 1000.0))

    # For Ubuntu
    # cmds = [
    #     "apt install -yqq python3-pip",
    #     "python3 -m pip install --no-cache-dir setuptools",
    #     "python3 -m pip install --no-cache-dir https://github.com/shadowsocks/shadowsocks/archive/master.zip",
    # ]
    #
    # for i in cmds:
    #     print("> " + i)
    #
    #     stdin, stdout, stderr = ssh.exec_command(i)
    #     stdout = stdout.read()
    #     result = stdout.decode() if stdout else stderr.read().decode()
    #     print(result)
    #     print("-" * 10)

    # ssh.exec_command("nohup ssserver --fast-open -p %d -k %s >ss.log" % (ss_port, ss_password), )

    stdin, stdout, stderr = ssh.exec_command(
        'docker run -d --rm -p %d:8388 python:3-alpine sh -c "python -m pip install --no-cache-dir https://github.com/shadowsocks/shadowsocks/archive/master.zip && ssserver --fast-open -p 8388 -k %s"' % (
            ss_port, ss_password))
    stdout = stdout.read().decode()
    print(stdout)

    stdin, stdout, stderr = ssh.exec_command("docker ps")
    stdout = stdout.read().decode()
    print(stdout)
    if stdout.find("python") > -1:
        print("ss start success")
        print("port check", port_check(host, ss_port))
        from created_callback import callback
        callback(host, ss_port, ss_password)
    else:
        print("start ss failed.")
    ssh.close()
    return True


def create_server():
    return vultr_call("POST", "server/create", api_key=api_key,
                      DCID=5,  # Los Angeles
                      VPSPLANID=201,  # 1024 MB RAM,25 GB SSD,1.00 TB BW 5$/mo
                      # OSID=365,  # Ubuntu 19.10 x64
                      OSID=179,  # CoreOS
                      # OSID=327,  # FreeBSD
                      # OSID=159,  # Custom
                      # ISOID=547596,  # alpine

                      # OSID=186,  # 'application'
                      # APPID=APP_ID,
                      label="auto_" + time.strftime('%Y%m%d-%H%M%S')

                      )


def destroy(SUBID):
    print("call destroy", SUBID)
    vultr_call("POST", "server/destroy", SUBID=SUBID, api_key=api_key)


def destroy_all():
    print("destroy all...")
    vps_list = vultr_call("GET", "server/list", api_key=api_key)
    for key in vps_list:
        print(vps_list[key])
        destroy(vps_list[key]["SUBID"])


if __name__ == "__main__":
    destroy_all()

    new_server = create_server()
    print("server created", new_server)
    new_sub_id = new_server["SUBID"]

    ip, password = get_new_server_ip_and_password(new_sub_id)

    server_starting_time = get_now_ms()
    ssh_install_and_run_ss(host=ip, port=22, user="root", password=password,
                           ss_port=16666, ss_password="qqnbyfl")
    print("wait exit to destroy_all")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        destroy_all()

import yaml
import time
import errno
import os
import traceback
import threading

from common.recordlog import logs
from conf.operationConfig import OperationConfig
from conf.setting import FILE_PATH
from yaml.scanner import ScannerError

# 是否将接口关联数据（token/订单号等）落盘到 extract.yaml。
# - 并行执行（pytest-xdist，pytest -n auto）时保持 False：数据只走进程内字典，
#   从根源上规避多进程并发读写同一文件导致的穿插损坏、脏数据、读到旧值等问题；
# 单进程调试或需要人工查看 extract.yaml 时改为 True，文件读写会走跨进程文件锁。
ENABLE_FILE_PERSIST = True

# 进程内共享数据：pytest-xdist 每个 worker 都是独立进程，模块级 dict 天然进程隔离。
# 登录 fixture 写入后，同进程内的用例都能读到，无需落盘，是并行场景下的主路径。
_PROCESS_DATA = {}
# 进程内读写锁：保证同一进程内多线程访问字典时操作的原子性。
_PROCESS_LOCK = threading.Lock()


class FileLock:
    """跨进程文件锁。

    基于 os.open(O_CREAT | O_EXCL) 原子创建锁文件实现，不依赖第三方库，
    兼容 Windows / Linux。进程异常退出时锁文件可能残留，超时后会抛错，
    不会永久阻塞等待。
    """

    def __init__(self, lock_path, timeout=5.0, poll_interval=0.05):
        self.lock_path = lock_path
        self.timeout = timeout
        self.poll_interval = poll_interval

    def __enter__(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode('utf-8'))
                finally:
                    os.close(fd)
                return self
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise
                if time.time() >= deadline:
                    raise TimeoutError(
                        '获取文件锁超时: {}，可能存在残留锁文件，请手动删除后重试'.format(self.lock_path))
                time.sleep(self.poll_interval)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            os.remove(self.lock_path)
        except OSError:
            pass


def get_testcase_yaml(file):
    testcase_list = []
    try:
        with open(file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            if len(data) <= 1:
                yam_data = data[0]
                base_info = yam_data.get('baseInfo')
                for ts in yam_data.get('testCase'):
                    param = [base_info, ts]
                    testcase_list.append(param)
                return testcase_list
            else:
                return data
    except UnicodeDecodeError:
        logs.error(f"[{file}]文件编码格式错误，--尝试使用utf-8编码解码YAML文件时发生了错误，请确保你的yaml文件是UTF-8格式！")
    except FileNotFoundError:
        logs.error(f'[{file}]文件未找到，请检查路径是否正确')
    except Exception as e:
        logs.error(f'获取【{file}】文件数据时出现未知错误: {str(e)}')


class ReadYamlData:
    """读写接口的YAML格式测试数据"""

    def __init__(self, yaml_file=None):
        if yaml_file is not None:
            self.yaml_file = yaml_file
        else:
            pass
        self.conf = OperationConfig()
        self.yaml_data = None

    @property
    def get_yaml_data(self):
        """
        获取测试用例yaml数据
        :param file: YAML文件
        :return: 返回list
        """
        # Loader=yaml.FullLoader表示加载完整的YAML语言，避免任意代码执行，无此参数控制台报Warning
        try:
            with open(self.yaml_file, 'r', encoding='utf-8') as f:
                self.yaml_data = yaml.safe_load(f)
                return self.yaml_data
        except Exception:
            logs.error(str(traceback.format_exc()))

    def write_yaml_data(self, value):
        """
        写入接口关联数据（token、订单号等），与 get_extract_data 成对使用。

        1) 先写进程内字典 _PROCESS_DATA：xdist 并行下无锁竞争、无 IO，是主路径；
        2) 若开启 ENABLE_FILE_PERSIST，则降级落盘 extract.yaml：
           合并 + 覆盖写（不再 append），并通过 FileLock + 临时文件原子替换，
           规避多进程并发读写导致的穿插损坏、重复 key、读到旧值等问题。

        :param value: 待写入数据，必须为 dict
        """
        if not isinstance(value, dict):
            logs.error('写入关联数据失败：value 必须为 dict 类型')
            return

        # 1) 进程内共享（主路径）
        with _PROCESS_LOCK:
            _PROCESS_DATA.update(value)

        # 2) 文件持久化（降级备选，默认关闭）
        if not ENABLE_FILE_PERSIST:
            return

        path = FILE_PATH['EXTRACT']
        lock_path = path + '.lock'
        try:
            with FileLock(lock_path):
                data = {}
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            data = yaml.safe_load(f) or {}
                    except yaml.YAMLError as e:
                        # 解析失败时兜底为空字典，避免一个脏文件导致整体崩溃
                        logs.error('解析 extract.yaml 失败，已用空数据兜底: %s' % e)
                        data = {}
                data.update(value)
                # 先写临时文件再原子替换，避免并发下读到写了一半的文件
                tmp_path = path + '.tmp'
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
                os.replace(tmp_path, path)
        except TimeoutError as e:
            logs.error('写入 extract.yaml 获取文件锁超时: %s' % e)
        except Exception:
            logs.error('写入 extract.yaml 失败: %s' % traceback.format_exc())

    def clear_yaml_data(self):
        """
        清空接口关联数据：同时清空进程内字典与 extract.yaml 文件。
        会话级 fixture 在测试开始时调用，保证每次运行都从一个干净状态开始。
        """
        with _PROCESS_LOCK:
            _PROCESS_DATA.clear()
        try:
            with open(FILE_PATH['EXTRACT'], 'w', encoding='utf-8') as f:
                f.truncate()
        except Exception:
            logs.error('清空 extract.yaml 失败: %s' % traceback.format_exc())

    def get_extract_data(self, node_name, default=None):
        """
        读取接口关联数据，与 write_yaml_data 成对使用。

        优先读进程内字典（xdist 下每个 worker 独立进程，天然隔离）；
        开启 ENABLE_FILE_PERSIST 且内存未命中时，降级读 extract.yaml。

        :param node_name: 关联数据的 key，如 token、orderNumber
        :param default: 未取到时的默认值
        """
        with _PROCESS_LOCK:
            if node_name in _PROCESS_DATA:
                return _PROCESS_DATA[node_name]

        if not ENABLE_FILE_PERSIST:
            logs.warning('关联数据 [%s] 未在进程内取到，请确认登录/前置接口是否已执行' % node_name)
            return default

        path = FILE_PATH['EXTRACT']
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return default
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            return data.get(node_name, default)
        except yaml.YAMLError as e:
            logs.error('解析 extract.yaml 失败: %s' % e)
        except Exception:
            logs.error('读取 extract.yaml 失败: %s' % traceback.format_exc())
        return default

    def get_extract_yaml(self, node_name, second_node_name=None):
        """
        读取关联数据，兼容旧的二级节点读取方式（second_node_name）。

        底层已改走 get_extract_data（进程内优先），保留此方法是为了
        不破坏 DebugTalk.get_extract_data 的既有调用链。
        """
        data = self.get_extract_data(node_name)
        if second_node_name is None:
            return data
        if isinstance(data, (dict, list)):
            try:
                return data[second_node_name]
            except (KeyError, IndexError, TypeError):
                logs.error('读取二级节点失败: %s[%s]' % (node_name, second_node_name))
                return None
        return data

    def get_testCase_baseInfo(self, case_info):
        """
        获取testcase yaml文件的baseInfo数据
        :param case_info: yaml数据，dict类型
        :return:
        """
        pass

    def get_method(self):
        """
        :param self:
        :return:
        """
        yal_data = self.get_yaml_data()
        metd = yal_data[0].get('method')
        return metd

    def get_request_parame(self):
        """
        获取yaml测试数据中的请求参数
        :return:
        """
        data_list = []
        yaml_data = self.get_yaml_data()
        del yaml_data[0]
        for da in yaml_data:
            data_list.append(da)
        return data_list
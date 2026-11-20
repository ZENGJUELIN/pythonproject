import shutil
import pytest
import os
import webbrowser
from conf.setting import REPORT_TYPE

if __name__ == '__main__':
    pytest.main(['-vs', '--alluredir=./report/temp', '--clean-alluredir', './testcase/Logistics API'])
    shutil.copy('./environment.xml', './report/temp/Logistics API.xml')
    os.system(f'allure serve ./report/temp')
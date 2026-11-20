import allure
import pytest

from common.readyaml import get_testcase_yaml
from base.apiutil import RequestBase
from base.generateId import m_id, c_id


@allure.feature(next(m_id) + '物流API模块')
class TestLogisticsAPI:

    # 场景，allure报告的目录结构
    @allure.story(next(c_id) + "获取下单物料信息")
    # 测试用例执行顺序设置
    @pytest.mark.run(order=1)
    # 参数化，yaml数据驱动
    @pytest.mark.parametrize('base_info,testcase', get_testcase_yaml("./testcase/Logistics API/Get Order.yaml"))
    def test_get_order(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

    @allure.story(next(c_id) + "货主（托运人）下订单")
    # 测试用例执行顺序设置
    @pytest.mark.run(order=2)
    # 参数化，yaml数据驱动
    @pytest.mark.parametrize('base_info,testcase', get_testcase_yaml("./testcase/Logistics API/xiadan.yaml"))
    def test_create_order(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

    @allure.story(next(c_id) + "集团接收订单")
    # 测试用例执行顺序设置
    @pytest.mark.run(order=3)
    # 参数化，yaml数据驱动
    @pytest.mark.parametrize('base_info,testcase', get_testcase_yaml("./testcase/Logistics API/jiedan.yaml"))
    def test_assign_order(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

    @allure.story(next(c_id) + "集团分配订单给物流公司")
    # 测试用例执行顺序设置
    @pytest.mark.run(order=4)
    # 参数化，yaml数据驱动
    @pytest.mark.parametrize('base_info,testcase', get_testcase_yaml("./testcase/Logistics API/fenpei.yaml"))
    def test_assign_order_to_company(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)
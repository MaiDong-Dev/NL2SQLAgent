"""
argparse 模块 可以自定义传入配置参数
不使用它就要在PyCharm中运行配置手动输入参数






argparse 模块让编写用户友好的命令行接口变得容易。
程序定义它需要哪些参数，argparse 将会知道如何从 sys.argv 解析它们
"""
import argparse

# 创建解析器
parser = argparse.ArgumentParser(
    prog='build_meta_knowledge',
    description='Build Meta Knowledge',
    epilog='Text at the bottom of the file')
parser.add_argument('filename')  # 位置参数
parser.add_argument('-c', '--count')  # 接受一个值的选项
parser.add_argument('-v', '--verbose',
                    action='store_true')  # 启用/禁用旗标
# 解析参数
args = parser.parse_args()
# 打印解析后的参数
print("\n")
print(f"文件名称: {args.filename}")
print(f"计数: {args.count}")
print(f"详细模式: {args.verbose}")

#   """
#   (.venv) PS D:\Projectfiler\SGGAgentStudy\NL2SQLAgentStudy\NL2SQLAgent_fanal> python -m app.scripts.bulid_meta_knowledge path/to/config.yaml -c 10
#
#
#   文件名称: path/to/config.yaml
#   计数: 10
#   详细模式: False
#   (.venv) PS D:\Projectfiler\SGGAgentStudy\NL2SQLAgentStudy\NL2SQLAgent_fanal> python -m app.scripts.bulid_meta_knowledge path/to/config.yaml -c 10 -v
#
#
#   文件名称: path/to/config.yaml
#   计数: 10
#   详细模式: True
#   (.venv) PS D:\Projectfiler\SGGAgentStudy\NL2SQLAgentStudy\NL2SQLAgent_fanal>
#   """
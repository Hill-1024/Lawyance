# 注意事项
- **不要把API_KEY传到仓库!!!**,把API_KEY存在根目录的‘.env’环境文件里(自己创建),内容格式形如`API_KEY="<此处填密钥>"`\
并在function_calling.py中修改服务提供商的url和模型名称
- 各模块已解耦,尽量不要修改非自己模块的内容,如果要修改请进行沟通
# 如何运行本地demo
```
python agent.py
```
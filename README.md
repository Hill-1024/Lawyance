# 注意事项
- **不要把API_KEY传到仓库!!!**,把API_KEY存在根目录的'.env'环境文件里(自己创建),内容格式形如`API_KEY="<此处填密钥>"`\
具体参考.env.example
- 各模块已解耦,尽量不要修改非自己模块的内容,如果要修改请进行沟通
# 如何运行demo
## 安装依赖
```
pnpm install
pip install -r requirements.txt
```
## 构建
```
pnpm run build
```

## 运行
```
pnpm run dev
```

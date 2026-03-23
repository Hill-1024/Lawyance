from function_calling import call, memory
from mcps import use_tools
import json

# Agent
if __name__ == '__main__':
    memory.append({"role": "user", "content": "介绍自己"})# 启动
    res = call(memory)
    print(res.content)
    memory.append({"role": "assistant", "content": res.content})
    while True:
        content = input()
        memory.append({"role": "user", "content": content})
        res = call(memory)
        if res.tool_calls:
            print(res.content)
            # 把模型的调用请求先存入上下文，保持对话历史完整
            memory.append(res)
            # 遍历大模型请求调用的工具（可能会同时调用多个）
            for tool_call in res.tool_calls:
                function_name = tool_call.function.name
                # 解析大模型提取出来的参数
                arguments = json.loads(tool_call.function.arguments)
                #转交工具请求给mcps.py
                result = use_tools(function_name,arguments)
                memory.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": result
                })

            # 携带查询到的结果，再次调用大模型
            final_message = call(memory)
            print(final_message.content)
            memory.append({"role": "assistant", "content": final_message.content})
        else:
            print(res.content)
            memory.append({"role": "assistant", "content": res.content})

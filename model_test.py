"""用一条短回复检查 MathPath 的 ChatGPT 授权与生成。"""

import sys

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from chatgpt_login import LoginError
from llm_client import MODEL, ModelError, generate_text, response_error, safe_error_code

PROMPT = "请只回复这句话，不添加其他内容：MathPath 连接成功。"


def main():
    print("正在使用 " + MODEL + " 测试生成，请稍候……", flush=True)
    text = generate_text(PROMPT)
    print("模型回答：")
    print(text)
    print("生成测试完成：已收到 response.completed。")


if __name__ == "__main__":
    try:
        main()
    except (ModelError, LoginError) as exc:
        print("生成测试未完成：" + str(exc))
        sys.exit(1)
    except APITimeoutError:
        print("生成测试未完成：请求超时，请反馈此提示。")
        sys.exit(1)
    except APIConnectionError:
        print("生成测试未完成：无法连接 OpenAI，请检查网络。")
        sys.exit(1)
    except APIStatusError as exc:
        print(f"生成测试未完成：HTTP {exc.status_code}，错误代码：{safe_error_code(exc.code)}。")
        sys.exit(1)
    except APIError as exc:
        print("生成测试未完成：" + str(response_error(exc.code)))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n生成测试已取消。")
        sys.exit(130)
    except Exception as exc:
        print("生成测试未完成，异常类型：" + type(exc).__name__ + "。请反馈这行提示。")
        sys.exit(1)

import asyncio
from src.container import global_container

async def main():
    try:
        router = global_container.llm_router()
        print("Providers:", list(router._providers.keys()))
        res, provider = await router.generate("Say hello", complexity="normal")
        print("Result:", res)
        print("Provider used:", provider)
    except Exception as e:
        print("Exception:", type(e).__name__, str(e))
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

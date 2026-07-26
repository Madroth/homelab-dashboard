from mcstatus import JavaServer

MINECRAFT_ADDR = "100.87.245.107:25565"


def get_status() -> dict:
    try:
        server = JavaServer.lookup(MINECRAFT_ADDR, timeout=2)
        status = server.status()
        return {
            'online': True,
            'players': status.players.online,
            'max_players': status.players.max,
            'version': status.version.name,
        }
    except Exception as e:
        return {'online': False, 'error': str(e)}


def get_status_text() -> str:
    status = get_status()
    if status['online']:
        return (f"Minecraft server is Online. "
                f"Players: {status['players']}/{status['max_players']}. "
                f"Version: {status['version']}")
    return f"Minecraft server is Offline or unreachable. Error: {status['error']}"

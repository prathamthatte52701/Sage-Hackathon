import logging
logger=logging.getLogger(__name__)
def authenticate(token: str):
    logger.info('auth attempt token=%s',token)
    return token.startswith('session-')

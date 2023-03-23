from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor
from envparse import env
from pytz import utc

env.read_envfile()

jobstores = {
    'default': RedisJobStore(
        host=env.str('REDIS_HOST'),
        port=env.int('REDIS_PORT'),
        password=env.str('REDIS_PASSWORD', default=None)
    )
}

executors = {
    'default': AsyncIOExecutor()
}

job_defaults = {
    'coalesce': False,
    'max_instances': 1
}

apscheduler = AsyncIOScheduler(jobstores=jobstores, executors=executors, job_defaults=job_defaults, timezone=utc)


def setup():
    apscheduler.start()


def stop():
    apscheduler.shutdown()
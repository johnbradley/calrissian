from cwltool.executors import MultithreadedJobExecutor
import logging

log = logging.getLogger("calrissian.executor")


class CalrissianExecutor(MultithreadedJobExecutor):

    def __init__(self, max_ram, max_cores):  # type: () -> None
        """
        Initialize a Calrissian Executor
        :param max_ram: Maximum RAM to use in megabytes
        :param max_cores: Maximum number of CPU cores to use
        """
        # MultithreadedJobExecutor sets self.max_ram and self.max_cores to the local machine's resources using psutil.
        # We can simply override these values after init, and the executor will use our provided values
        super(CalrissianExecutor, self).__init__()
        self.max_ram = max_ram
        self.max_cores = max_cores
        log.debug('Initialized executor to allow {} MB RAM and {} CPU cores'.format(self.max_ram, self.max_cores))

    def select_resources(self, request, runtime_context):
        log.debug('CalrissianExecutor.select_resources: {}'.format(request))
        return super(CalrissianExecutor, self).select_resources(request, runtime_context)

    def run_jobs(self,
                 process,           # type: Process
                 job_order_object,  # type: Dict[Text, Any]
                 logger,
                 runtime_context     # type: RuntimeContext
                ):
        return super(CalrissianExecutor, self).run_jobs(process, job_order_object, logger, runtime_context)

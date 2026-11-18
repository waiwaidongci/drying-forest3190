from ..services import pair_runs
class PairRunsController:
    list=staticmethod(pair_runs.list_pair_runs)
    create=staticmethod(pair_runs.create_pair_run)
    @staticmethod
    def get(db,id):return pair_runs.detail(db,id)
    retry=staticmethod(pair_runs.retry_pair_run)

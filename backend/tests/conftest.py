import os
import tempfile

# 在导入任何 src 模块前固定测试数据库与产物目录，避免写入工作区。
_TMP = tempfile.mkdtemp(prefix='drying-forest-tests-')
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + os.path.join(_TMP, 'test.db'))
os.environ.setdefault('ARTIFACT_DIR', os.path.join(_TMP, 'artifacts'))
os.environ.setdefault('SEED_DEMO', 'false')
os.environ.setdefault('JWT_SECRET', 'test-secret')

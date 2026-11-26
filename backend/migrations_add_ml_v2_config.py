"""数据库迁移：为 scheduler_config 表添加 ML模型V2定时训练配置字段

运行方式:
    cd backend
    python migrations_add_ml_v2_config.py

或者直接执行SQL:
    ALTER TABLE scheduler_config ADD COLUMN ml_v2_train_enabled BOOLEAN DEFAULT FALSE;
    ALTER TABLE scheduler_config ADD COLUMN ml_v2_train_day_of_week INTEGER DEFAULT 2;
    ALTER TABLE scheduler_config ADD COLUMN ml_v2_train_time VARCHAR(5) DEFAULT '21:00';
    ALTER TABLE scheduler_config ADD COLUMN ml_v2_train_days INTEGER DEFAULT 500;
    ALTER TABLE scheduler_config ADD COLUMN ml_v2_train_stocks INTEGER DEFAULT 100;
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "backend"))

from sqlalchemy import text
from app.core.database import SessionLocal

def run_migration():
    db = SessionLocal()
    try:
        # 检查列是否已存在
        result = db.execute(text("""
            SELECT name FROM pragma_table_info('scheduler_config')
        """)).fetchall()
        existing_columns = {row[0] for row in result}

        new_columns = {
            "ml_v2_train_enabled": "BOOLEAN DEFAULT FALSE",
            "ml_v2_train_day_of_week": "INTEGER DEFAULT 2",
            "ml_v2_train_time": "VARCHAR(5) DEFAULT '21:00'",
            "ml_v2_train_days": "INTEGER DEFAULT 500",
            "ml_v2_train_stocks": "INTEGER DEFAULT 100",
        }

        added = []
        for col_name, col_def in new_columns.items():
            if col_name not in existing_columns:
                sql = f"ALTER TABLE scheduler_config ADD COLUMN {col_name} {col_def}"
                print(f"执行: {sql}")
                db.execute(text(sql))
                added.append(col_name)

        db.commit()

        if added:
            print(f"\n✅ 迁移成功！新增字段: {', '.join(added)}")
        else:
            print("\n✅ 所有字段已存在，无需迁移。")

    except Exception as e:
        db.rollback()
        print(f"❌ 迁移失败: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()

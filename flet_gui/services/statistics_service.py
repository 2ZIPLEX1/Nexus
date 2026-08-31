"""
Statistics service - integrates TradingStatistics with GUI.
"""

from pathlib import Path
from datetime import datetime
from typing import Optional
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.statistics import TradingStatistics
from flet_gui.state.app_state import AppState
from src.logger import get_logger

logger = get_logger(__name__)


class StatisticsService:
    """Service for statistics and data export in GUI."""

    def __init__(self, state: AppState, db_service):
        """Initialize statistics service."""
        self.state = state
        self.db_service = db_service
        self.statistics = TradingStatistics(db_service.db)
        logger.info("StatisticsService initialized")

    def get_summary(self, days: int = 30) -> dict:
        """Get trading summary for specified period."""
        try:
            summary = self.statistics.get_summary(days=days)
            return summary
        except Exception as e:
            logger.error(f"Failed to get summary: {e}")
            self.state.add_log(f"[ERROR] Failed to get statistics: {str(e)}")
            return {}

    def get_daily_stats(self, days: int = 7) -> list:
        """Get daily statistics."""
        try:
            return self.statistics.get_daily_stats(days=days)
        except Exception as e:
            logger.error(f"Failed to get daily stats: {e}")
            return []

    def get_top_items(self, limit: int = 10, by: str = 'profit') -> list:
        """Get top items by profit, trades, or ROI."""
        try:
            return self.statistics.get_top_items(limit=limit, by=by)
        except Exception as e:
            logger.error(f"Failed to get top items: {e}")
            return []

    def generate_report(self, days: int = 30) -> str:
        """Generate text report."""
        try:
            return self.statistics.generate_report(days=days)
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            return f"Error generating report: {e}"

    def export_to_csv(self, data_type: str = 'all', days: int = 30) -> Optional[Path]:
        """
        Export data to CSV files.

        Args:
            data_type: 'purchased', 'sold', 'profitable', or 'all'
            days: Number of days to export

        Returns:
            Path to export directory if successful, None otherwise
        """
        try:
            self.state.add_log("[INFO] Exporting data to CSV...")

            # Create exports directory
            export_dir = Path("exports")
            export_dir.mkdir(exist_ok=True)

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = export_dir / f"trading_data_{timestamp}.csv"

            # Export data
            success = self.statistics.export_to_csv(
                output_file=str(output_file),
                data_type=data_type,
                days=days
            )

            if success:
                self.state.add_log(f"[SUCCESS] Data exported to {export_dir}")
                if data_type == 'all':
                    self.state.add_log(f"   - {output_file.stem}_purchased.csv")
                    self.state.add_log(f"   - {output_file.stem}_sold.csv")
                    self.state.add_log(f"   - {output_file.stem}_profitable.csv")
                return export_dir
            else:
                self.state.add_log("[ERROR] Export failed")
                return None

        except Exception as e:
            logger.error(f"Failed to export data: {e}")
            self.state.add_log(f"[ERROR] Export failed: {str(e)}")
            return None

    def export_to_json(self, data_type: str = 'all', days: int = 30) -> Optional[Path]:
        """
        Export data to JSON files.

        Args:
            data_type: 'purchased', 'sold', 'profitable', 'summary', or 'all'
            days: Number of days to export

        Returns:
            Path to export file if successful, None otherwise
        """
        import json

        try:
            self.state.add_log("[INFO] Exporting data to JSON...")

            # Create exports directory
            export_dir = Path("exports")
            export_dir.mkdir(exist_ok=True)

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = export_dir / f"trading_data_{timestamp}.json"

            data = {}

            if data_type in ['summary', 'all']:
                data['summary'] = self.get_summary(days=days)

            if data_type in ['purchased', 'all']:
                ready = self.db_service.db.get_items_ready_to_sell()
                on_hold = self.db_service.db.get_items_on_hold()
                data['purchased_items'] = ready + on_hold

            if data_type in ['sold', 'all']:
                data['sold_items'] = self.db_service.db.get_recent_sales(limit=1000)

            if data_type in ['profitable', 'all']:
                min_profit = self.state.config.get('scanner_min_profit', -5.0) if hasattr(self.state, 'config') else -5.0
                data['profitable_items'] = self.db_service.db.get_active_profitable_items(min_profit=min_profit, limit=1000)

            if data_type in ['orders', 'all']:
                data['active_orders'] = self.db_service.db.get_active_orders()

            # Write JSON file
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)

            self.state.add_log(f"[SUCCESS] Data exported to {output_file}")
            return output_file

        except Exception as e:
            logger.error(f"Failed to export JSON: {e}")
            self.state.add_log(f"[ERROR] JSON export failed: {str(e)}")
            return None

"""
Nepali date conversion utilities for IRD compliance
Handles conversion between AD (Gregorian) and BS (Bikram Sambat) calendars
"""

import datetime
from typing import Tuple, Optional


class NepaliDateConverter:
    """Convert dates between AD (Gregorian) and BS (Bikram Sambat) calendars"""
    
    # Reference date: 2000-01-01 AD = 2056-09-17 BS
    REFERENCE_AD = datetime.date(2000, 1, 1)
    REFERENCE_BS = (2056, 9, 17)
    
    # Days in each month in BS (can vary for leap years)
    BS_MONTH_DAYS_NORMAL = [30, 32, 31, 32, 31, 30, 30, 30, 30, 29, 30, 30]
    BS_MONTH_DAYS_LEAP = [30, 32, 31, 32, 31, 30, 30, 30, 30, 30, 30, 30]
    
    @classmethod
    def ad_to_bs(cls, ad_date: datetime.date) -> Tuple[int, int, int]:
        """
        Convert AD date to BS date
        Returns: (year_bs, month_bs, day_bs)
        """
        if not isinstance(ad_date, datetime.date):
            raise ValueError("ad_date must be a date object")
        
        # Calculate days difference from reference
        days_diff = (ad_date - cls.REFERENCE_AD).days
        
        # Convert to BS starting from reference
        bs_year, bs_month, bs_day = cls.REFERENCE_BS
        
        # Add days difference
        current_bs_date = cls._add_days_to_bs(bs_year, bs_month, bs_day, days_diff)
        
        return current_bs_date
    
    @classmethod
    def bs_to_ad(cls, bs_year: int, bs_month: int, bs_day: int) -> datetime.date:
        """
        Convert BS date to AD date
        Returns: datetime.date in AD
        """
        # Validate BS date
        if not cls._is_valid_bs_date(bs_year, bs_month, bs_day):
            raise ValueError(f"Invalid BS date: {bs_year}-{bs_month}-{bs_day}")
        
        # Calculate days difference from reference
        days_diff = cls._calculate_days_diff_from_reference(bs_year, bs_month, bs_day)
        
        # Convert to AD
        ad_date = cls.REFERENCE_AD + datetime.timedelta(days=days_diff)
        
        return ad_date
    
    @classmethod
    def get_fiscal_year(cls, ad_date: datetime.date) -> Tuple[str, str]:
        """
        Get fiscal year for given AD date
        Returns: (year_bs, year_ad) in format "2081/82", "2024/25"
        """
        # Nepal fiscal year runs from Shrawan (approx July 16) to Ashadh (approx July 15)
        # Approximate: fiscal year starts in mid-July
        
        year = ad_date.year
        if ad_date.month < 7 or (ad_date.month == 7 and ad_date.day < 16):
            fiscal_year_start = year - 1
            fiscal_year_end = year
        else:
            fiscal_year_start = year
            fiscal_year_end = year + 1
        
        # Convert to BS (approximate)
        bs_start = fiscal_year_start + 56
        bs_end = fiscal_year_end + 56
        
        year_bs = f"{bs_start}/{(bs_end % 100):02d}"
        year_ad = f"{fiscal_year_start}/{(fiscal_year_end % 100):02d}"
        
        return year_bs, year_ad
    
    @classmethod
    def format_bs_date(cls, bs_year: int, bs_month: int, bs_day: int) -> str:
        """Format BS date as string"""
        return f"{bs_year:04d}-{bs_month:02d}-{bs_day:02d}"
    
    @classmethod
    def parse_bs_date(cls, bs_date_str: str) -> Tuple[int, int, int]:
        """Parse BS date string 'YYYY-MM-DD'"""
        try:
            year, month, day = map(int, bs_date_str.split('-'))
            return year, month, day
        except (ValueError, AttributeError):
            raise ValueError(f"Invalid BS date format: {bs_date_str}")
    
    @classmethod
    def is_leap_year_bs(cls, bs_year: int) -> bool:
        """Check if BS year is a leap year (simplified)"""
        # BS leap years follow a complex pattern, this is simplified
        # Generally every 4 years with exceptions
        return bs_year % 4 == 0
    
    @classmethod
    def _add_days_to_bs(cls, bs_year: int, bs_month: int, bs_day: int, days: int) -> Tuple[int, int, int]:
        """Add days to BS date"""
        current_year, current_month, current_day = bs_year, bs_month, bs_day
        
        for _ in range(days):
            current_day += 1
            
            # Check if we need to move to next month
            month_days = cls._get_bs_month_days(current_year, current_month)
            if current_day > month_days:
                current_day = 1
                current_month += 1
                
                # Check if we need to move to next year
                if current_month > 12:
                    current_month = 1
                    current_year += 1
        
        return current_year, current_month, current_day
    
    @classmethod
    def _calculate_days_diff_from_reference(cls, bs_year: int, bs_month: int, bs_day: int) -> int:
        """Calculate days difference from reference BS date"""
        days_diff = 0
        current_year, current_month, current_day = cls.REFERENCE_BS
        
        # Move forward until we reach the target date
        while (current_year, current_month, current_day) != (bs_year, bs_month, bs_day):
            days_diff += 1
            current_day += 1
            
            # Check month rollover
            month_days = cls._get_bs_month_days(current_year, current_month)
            if current_day > month_days:
                current_day = 1
                current_month += 1
                
                # Check year rollover
                if current_month > 12:
                    current_month = 1
                    current_year += 1
        
        return days_diff
    
    @classmethod
    def _get_bs_month_days(cls, bs_year: int, bs_month: int) -> int:
        """Get number of days in BS month"""
        if cls.is_leap_year_bs(bs_year):
            return cls.BS_MONTH_DAYS_LEAP[bs_month - 1]
        else:
            return cls.BS_MONTH_DAYS_NORMAL[bs_month - 1]
    
    @classmethod
    def _is_valid_bs_date(cls, bs_year: int, bs_month: int, bs_day: int) -> bool:
        """Validate BS date"""
        if bs_year < 1900 or bs_year > 2200:
            return False
        if bs_month < 1 or bs_month > 12:
            return False
        
        month_days = cls._get_bs_month_days(bs_year, bs_month)
        return 1 <= bs_day <= month_days


class NepaliFiscalYear:
    """Handle Nepal fiscal year operations"""
    
    @classmethod
    def get_current_fiscal_year(cls, ad_date: Optional[datetime.date] = None) -> Tuple[str, str, datetime.date, datetime.date]:
        """
        Get current fiscal year information
        Returns: (year_bs, year_ad, start_date_ad, end_date_ad)
        """
        if ad_date is None:
            ad_date = datetime.date.today()
        
        year_bs, year_ad = NepaliDateConverter.get_fiscal_year(ad_date)
        
        # Approximate fiscal year dates (Shrawan 1 to Ashadh end)
        year_start = int(year_ad.split('/')[0])
        year_end = int(year_ad.split('/')[1])
        
        start_date = datetime.date(year_start, 7, 16)  # Approximate Shrawan 1
        end_date = datetime.date(year_end, 7, 15)     # Approximate Ashadh 30
        
        return year_bs, year_ad, start_date, end_date
    
    @classmethod
    def get_fiscal_year_months(cls, fiscal_year_bs: str) -> list:
        """Get list of months in fiscal year with Nepali names"""
        nepali_months = [
            'Shrawan', 'Bhadra', 'Ashwin', 'Kartik', 'Mangsir', 'Poush',
            'Magh', 'Falgun', 'Chaitra', 'Baisakh', 'Jestha', 'Ashadh'
        ]
        
        return nepali_months
    
    @classmethod
    def get_month_number(cls, month_name: str) -> int:
        """Get month number from Nepali month name"""
        month_map = {
            'Shrawan': 1, 'Bhadra': 2, 'Ashwin': 3, 'Kartik': 4,
            'Mangsir': 5, 'Poush': 6, 'Magh': 7, 'Falgun': 8,
            'Chaitra': 9, 'Baisakh': 10, 'Jestha': 11, 'Ashadh': 12
        }
        return month_map.get(month_name, 1)


# Utility functions for easy access
def ad_to_bs(ad_date: datetime.date) -> Tuple[int, int, int]:
    """Convert AD date to BS"""
    return NepaliDateConverter.ad_to_bs(ad_date)


def bs_to_ad(bs_year: int, bs_month: int, bs_day: int) -> datetime.date:
    """Convert BS date to AD"""
    return NepaliDateConverter.bs_to_ad(bs_year, bs_month, bs_day)


def get_fiscal_year(ad_date: datetime.date = None) -> Tuple[str, str]:
    """Get fiscal year for date"""
    if ad_date is None:
        ad_date = datetime.date.today()
    return NepaliDateConverter.get_fiscal_year(ad_date)

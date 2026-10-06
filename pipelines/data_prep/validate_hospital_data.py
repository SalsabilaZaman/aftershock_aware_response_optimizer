"""
Hospital Data Validation Tool
Validates capacity data for the medical model.
Usage: python validate_hospital_data.py --input data_processed/hospitals/hospital_data.csv
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys

class HospitalDataValidator:
    """Validate hospital capacity data."""
    
    BOUNDS = {
        'lat_min': 36.5,
        'lat_max': 38.5,
        'lon_min': 35.5,
        'lon_max': 38.5
    }
    
    BENCHMARKS = {
        'beds_per_1000_pop': (3.5, 4.0),
        'doctors_per_1000_pop': (0.44, 0.55),
        'nurses_per_1000_pop': (0.55, 0.66),
        'bed_to_doctor_ratio': (4, 8),
        'bed_to_nurse_ratio': (1.5, 3),
        'icu_fraction': 0.15,
    }
    
    REQUIRED_COLUMNS = [
        'hospital_id', 'hospital_name', 'latitude', 'longitude',
        'facility_type', 'bed_capacity_icu', 'bed_capacity_general',
        'bed_capacity_total', 'outpatient_capacity',
        'n_doctors_pre', 'n_nurses_pre', 'operational_capacity'
    ]
    
    def __init__(self, filepath):
        self.filepath = Path(filepath)
        self.df = pd.read_csv(filepath)
        self.warnings = []
        self.errors = []
        
    def validate(self):
        print(f"\n{'='*70}")
        print(f"VALIDATING HOSPITAL DATA: {self.filepath.name}")
        print(f"{'='*70}")
        
        self.check_columns()
        self.check_completeness()
        self.check_geographic_bounds()
        self.check_capacity_logic()
        self.check_staffing_ratios()
        self.check_consistency()
        
        self.print_report()
        return len(self.errors) == 0
    
    def check_columns(self):
        missing = set(self.REQUIRED_COLUMNS) - set(self.df.columns)
        if missing:
            self.errors.append(f"Missing columns: {missing}")
        else:
            print("All required columns present")
    
    def check_completeness(self):
        null_counts = self.df.isnull().sum()
        if null_counts.sum() > 0:
            self.errors.append(f"Found {null_counts.sum()} missing values:")
            for col, count in null_counts[null_counts > 0].items():
                self.errors[-1] += f"\n   {col}: {count}"
        else:
            print("No missing values")
    
    def check_geographic_bounds(self):
        invalid_lat = ~self.df['latitude'].between(
            self.BOUNDS['lat_min'], self.BOUNDS['lat_max']
        )
        invalid_lon = ~self.df['longitude'].between(
            self.BOUNDS['lon_min'], self.BOUNDS['lon_max']
        )
        
        invalid = self.df[invalid_lat | invalid_lon]
        if len(invalid) > 0:
            self.warnings.append(
                f"{len(invalid)} hospitals outside expected bounds:"
            )
            for _, row in invalid.iterrows():
                self.warnings.append(
                    f"   {row['hospital_id']}: ({row['latitude']:.2f}, "
                    f"{row['longitude']:.2f})"
                )
        else:
            print("All coordinates within Kahramanmaraş bounds")
    
    def check_capacity_logic(self):
        total_calc = (self.df['bed_capacity_icu'] + 
                      self.df['bed_capacity_general'])
        mismatch = self.df[self.df['bed_capacity_total'] != total_calc]
        
        if len(mismatch) > 0:
            self.errors.append(
                f"{len(mismatch)} hospitals: bed_capacity_total ≠ "
                f"icu + general"
            )
            for _, row in mismatch.iterrows():
                expected = row['bed_capacity_icu'] + row['bed_capacity_general']
                self.errors[-1] += (
                    f"\n   {row['hospital_id']}: Total={row['bed_capacity_total']}, "
                    f"but ICU+General={expected}"
                )
        else:
            print("Bed capacity totals correct (ICU + General)")
        
        expected_outpatient = 3.0 * self.df['bed_capacity_total']
        ratio = self.df['outpatient_capacity'] / expected_outpatient
        
        suspicious = self.df[(ratio < 0.8) | (ratio > 1.2)]
        if len(suspicious) > 0:
            self.warnings.append(
                f"{len(suspicious)} hospitals: outpatient_capacity ratio "
                f"deviates from 3×bed_capacity:"
            )
            for _, row in suspicious.iterrows():
                expected = 3.0 * row['bed_capacity_total']
                ratio_val = row['outpatient_capacity'] / expected
                self.warnings.append(
                    f"   {row['hospital_id']}: {ratio_val:.2f}× "
                    f"(expected ~1.0)"
                )
        else:
            print("Outpatient capacity reasonable (ratio ~3.0×beds)")
    
    def check_staffing_ratios(self):
        bed_to_doc = self.df['bed_capacity_total'] / self.df['n_doctors_pre']
        bed_to_nurse = self.df['bed_capacity_total'] / self.df['n_nurses_pre']
        
        min_doc, max_doc = self.BENCHMARKS['bed_to_doctor_ratio']
        min_nurse, max_nurse = self.BENCHMARKS['bed_to_nurse_ratio']
        
        suspect_docs = self.df[
            (bed_to_doc < min_doc) | (bed_to_doc > max_doc)
        ]
        suspect_nurses = self.df[
            (bed_to_nurse < min_nurse) | (bed_to_nurse > max_nurse)
        ]
        
        if len(suspect_docs) > 0:
            self.warnings.append(
                f"{len(suspect_docs)} hospitals: unusual bed-to-doctor ratio "
                f"(benchmarks: {min_doc}-{max_doc}):"
            )
            for _, row in suspect_docs.iterrows():
                ratio = bed_to_doc.loc[row.name]
                self.warnings.append(
                    f"   {row['hospital_id']}: {ratio:.1f} beds/doctor"
                )
        
        if len(suspect_nurses) > 0:
            self.warnings.append(
                f"{len(suspect_nurses)} hospitals: unusual bed-to-nurse ratio "
                f"(benchmarks: {min_nurse}-{max_nurse}):"
            )
            for _, row in suspect_nurses.iterrows():
                ratio = bed_to_nurse.loc[row.name]
                self.warnings.append(
                    f"   {row['hospital_id']}: {ratio:.1f} beds/nurse"
                )
        
        if len(suspect_docs) == 0 and len(suspect_nurses) == 0:
            print("Staffing ratios within Turkish health system benchmarks")
    
    def check_consistency(self):
        type_checks = {
            'Hospital': {'min_beds': 50, 'min_doctors': 5},
            'Health Centre': {'min_beds': 20, 'min_doctors': 3},
            'Clinic': {'min_beds': 0, 'min_doctors': 0},
        }
        
        for idx, row in self.df.iterrows():
            ftype = row['facility_type']
            if ftype not in type_checks:
                self.warnings.append(
                    f"{row['hospital_id']}: unknown facility_type '{ftype}'"
                )
                continue
            
            min_beds = type_checks[ftype]['min_beds']
            if row['bed_capacity_total'] < min_beds:
                self.warnings.append(
                    f"{row['hospital_id']}: type says '{ftype}' but only "
                    f"{row['bed_capacity_total']} beds (expected >{min_beds})"
                )
    
    def print_report(self):
        print(f"\nSummary:")
        print(f"  Hospitals: {len(self.df)}")
        print(f"  Total beds: {self.df['bed_capacity_total'].sum()}")
        print(f"  Total doctors: {self.df['n_doctors_pre'].sum()}")
        print(f"  Total nurses: {self.df['n_nurses_pre'].sum()}")
        
        if self.errors:
            print(f"\nERRORS ({len(self.errors)}):")
            for err in self.errors:
                print(f"  {err}")
        
        if self.warnings:
            print(f"\nWARNINGS ({len(self.warnings)}):")
            for warn in self.warnings:
                print(f"  {warn}")
        
        if not self.errors and not self.warnings:
            print("\nVALIDATION PASSED - Data ready for model integration")
        
        print(f"\n{'='*70}\n")
    
    def export_for_model(self, output_path=None):
        if output_path is None:
            output_path = self.filepath.parent / 'hospital_data_VALIDATED.csv'
        
        ordered_cols = self.REQUIRED_COLUMNS
        df_export = self.df[ordered_cols].copy()
        
        df_export.to_csv(output_path, index=False)
        print(f"Exported model-ready data to: {output_path}")
        return df_export


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Validate hospital capacity data'
    )
    parser.add_argument('--input', type=str, default='data_processed/hospitals/hospital_data.csv',
                        help='Path to hospital data CSV file')
    parser.add_argument('--export', action='store_true',
                        help='Export to model-ready format after validation')
    
    args = parser.parse_args()
    
    if not Path(args.input).exists():
        print(f"File not found: {args.input}")
        print(f"\nCreate hospital data file or use template:")
        print(f"   cp data/hospital_data_TEMPLATE.csv {args.input}")
        sys.exit(1)
    
    validator = HospitalDataValidator(args.input)
    success = validator.validate()
    
    if args.export and success:
        validator.export_for_model()
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())

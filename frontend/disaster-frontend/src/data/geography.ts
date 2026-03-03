import { loadCSV } from './csvLoader'

export type DistrictGeo = {
  state_code: string
  district_code: string
}

export async function loadDistrictGeography(): Promise<DistrictGeo[]> {
  return loadCSV<DistrictGeo>(
    '/core_engine/data/processed/new_data/clean_district_codes.csv'
  )
}

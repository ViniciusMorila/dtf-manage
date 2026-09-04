from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.models.production_history import BatchRollSettingsSnapshot
from dtf_manager.models.production_validation import ProductionIssue, ProductionValidationResult
from dtf_manager.services.print_plan_service import build_dtf_print_plan
from dtf_manager.services.production_history_repository import ProductionHistoryRepository
from dtf_manager.services.production_history_service import batch_matches, create_production_batch_snapshot


class ProductionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/"A.png"; self.path.write_bytes(b"snapshot only")
        art=LinkedArt("a","A.png",str(self.path),3,"manual")
        item=ImportedOrderItem("i","o","ORDER-1","Produto Teste","listing","SKU TESTE","Azul","azul",None,None,1.0,2,[art],"linked")
        self.orders=[ImportedOrder("o","ORDER-1","UP-1","Shopee","Loja",[item])]
        self.plan=build_dtf_print_plan(self.orders,validate_files=False)
        warning=ProductionIssue("w","warning","HIGH","Confira")
        self.validation=ProductionValidationResult(warnings=(warning,))
        self.settings=BatchRollSettingsSnapshot(57,0.5,300,True,100)
        self.now=datetime(2026,9,1,14,35,tzinfo=timezone.utc)

    def snapshot(self,operation="op",number="DTF-20260901-001"):
        return create_production_batch_snapshot(self.orders,self.plan,self.validation,self.settings,batch_number=number,operation_id=operation,now=self.now)

    def test_snapshot_formula_summary_settings_and_warning(self):
        batch=self.snapshot(); art=batch.orders[0].items[0].arts[0]
        self.assertEqual((2,3,6),(batch.orders[0].items[0].product_quantity,art.copies_per_product,art.final_copies))
        self.assertEqual(6,batch.summary.total_print_copies); self.assertEqual(2,batch.summary.product_unit_count)
        self.assertEqual(57,batch.roll_settings.film_width_cm); self.assertEqual(1,batch.validation.warning_count)

    def test_snapshot_is_immutable_after_source_replacement(self):
        batch=self.snapshot(); self.orders[0]=replace(self.orders[0],items=[])
        self.assertEqual("Produto Teste",batch.orders[0].items[0].product_name)

    def test_multiple_arts_preserve_individual_totals(self):
        item=replace(self.orders[0].items[0],product_quantity=3,linked_arts=[replace(self.orders[0].items[0].linked_arts[0],copies_per_product=1),LinkedArt("b","back.png",str(Path(self.folder.name)/"back.png"),1,"manual")])
        orders=[replace(self.orders[0],items=[item])]; plan=build_dtf_print_plan(orders,validate_files=False)
        batch=create_production_batch_snapshot(orders,plan,ProductionValidationResult(),self.settings,batch_number="x",operation_id="x",now=self.now)
        self.assertEqual([3,3],[art.final_copies for art in batch.orders[0].items[0].arts])

    def test_repository_persists_searches_numbers_deletes_and_is_idempotent(self):
        storage=Path(self.folder.name)/"history.json"; repo=ProductionHistoryRepository(storage)
        first=repo.save(self.snapshot()); self.assertIs(first,repo.save(self.snapshot()))
        repo.save(self.snapshot("op2","DTF-20260901-002")); self.assertEqual("DTF-20260901-003",repo.next_batch_number(self.now))
        loaded=ProductionHistoryRepository(storage); self.assertEqual(2,len(loaded.list_all()))
        for query in ("DTF-20260901","ORDER-1","SKU TESTE","Produto Teste","A.png"): self.assertTrue(batch_matches(first,query))
        self.path.unlink(); self.assertEqual("A.png",loaded.list_all()[0].arts[0].file_name)
        loaded.delete(first.id); self.assertEqual(1,len(loaded.list_all()))

    def test_same_filename_different_paths_remain_distinct(self):
        second=Path(self.folder.name)/"other"/"A.png"
        item=replace(self.orders[0].items[0],linked_arts=[self.orders[0].items[0].linked_arts[0],LinkedArt("b","A.png",str(second),1,"manual")])
        orders=[replace(self.orders[0],items=[item])]; plan=build_dtf_print_plan(orders,validate_files=False)
        batch=create_production_batch_snapshot(orders,plan,ProductionValidationResult(),self.settings,batch_number="x",operation_id="x",now=self.now)
        self.assertEqual(2,len(batch.arts)); self.assertNotEqual(batch.arts[0].file_reference_snapshot,batch.arts[1].file_reference_snapshot)


if __name__ == "__main__": unittest.main()

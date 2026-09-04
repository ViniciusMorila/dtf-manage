from dataclasses import replace
from datetime import datetime, timezone
import unittest

from dtf_manager.models.imported_order import ImportedOrder, ImportedOrderItem, LinkedArt
from dtf_manager.models.production_history import BatchRollSettingsSnapshot
from dtf_manager.models.production_validation import ProductionValidationResult
from dtf_manager.services.import_history_analyzer import analyze_imported_orders_against_history, build_order_production_fingerprint, set_order_selection
from dtf_manager.services.print_plan_service import build_dtf_print_plan
from dtf_manager.services.production_history_service import create_production_batch_snapshot


class ImportHistoryAnalyzerTests(unittest.TestCase):
    def item(self,id="i",listing="10",sku="001234",variant="20",raw="Preta,G",normalized="preta,g",quantity=1,name="Produto",image=None,price=10.0):
        return ImportedOrderItem(id,"o","A",name,listing,sku,raw,normalized,variant,image,price,quantity,[],"unlinked")

    def order(self,number="A",items=None):
        return ImportedOrder("o",number,None,None,None,items or [self.item()])

    def historical(self,order=None,number="DTF-20260901-001",when=None):
        order=order or self.order(); plan=build_dtf_print_plan([replace(order,items=[replace(i,linked_arts=[],link_status="unlinked") for i in order.items])],validate_files=False) if False else None
        # History snapshot needs a plan only for aggregation; item comparison is independent of linked arts.
        from dtf_manager.models.print_plan import DTFOrderPlan
        plan=DTFOrderPlan(1,len(order.items),0,())
        return create_production_batch_snapshot([order],plan,ProductionValidationResult(),BatchRollSettingsSnapshot(None,None,None,None,None),batch_number=number,operation_id=number,now=when or datetime(2026,9,1,tzinfo=timezone.utc))

    def classification(self,current,batches): return analyze_imported_orders_against_history([current],batches).orders[0]

    def test_new_order_is_selected(self):
        result=self.classification(self.order("B"),[self.historical()]); self.assertEqual("new",result.classification); self.assertTrue(result.selected_for_current_batch)

    def test_equal_order_is_already_processed_and_unselected(self):
        result=self.classification(self.order(),[self.historical()]); self.assertEqual("already_processed",result.classification); self.assertFalse(result.selected_for_current_batch)

    def test_processed_order_restores_saved_art_links_and_quantity(self):
        art = LinkedArt("a", "arte.png", "C:/artes/arte.png", 3, "manual", 12.5, 20.0)
        historical_order = self.order(items=[replace(self.item(), linked_arts=[art], link_status="linked")])
        result = self.classification(self.order(), [self.historical(historical_order)])
        restored = result.order.items[0]
        self.assertEqual("linked", restored.link_status)
        self.assertEqual(("arte.png", 3, 12.5, 20.0), (
            restored.linked_arts[0].file_name,
            restored.linked_arts[0].copies_per_product,
            restored.linked_arts[0].width_cm,
            restored.linked_arts[0].height_cm,
        ))

    def test_quantity_change_is_explained(self):
        result=self.classification(self.order(items=[self.item(quantity=2)]),[self.historical()]); self.assertEqual("changed",result.classification); self.assertIn("QUANTITY_CHANGED",{d.code for d in result.differences})

    def test_added_removed_and_repeated_items_preserve_multiplicity(self):
        old=self.order(items=[self.item("i1"),self.item("i2")]); current=self.order(items=[self.item("i1")]); result=self.classification(current,[self.historical(old)]); self.assertEqual("changed",result.classification); self.assertIn("ITEM_REMOVED",{d.code for d in result.differences})
        added=self.classification(old,[self.historical(current)]); self.assertIn("ITEM_ADDED",{d.code for d in added.differences})

    def test_line_order_does_not_matter(self):
        a=self.item("a",sku="A"); b=self.item("b",sku="B"); old=self.order(items=[a,b]); current=self.order(items=[b,a]); self.assertEqual("already_processed",self.classification(current,[self.historical(old)]).classification)

    def test_commercial_fields_are_ignored(self):
        current=self.order(items=[self.item(name="Novo título",image="new",price=99)]); self.assertEqual("already_processed",self.classification(current,[self.historical()]).classification)

    def test_normalized_variation_and_string_sku(self):
        old=self.order(items=[self.item(raw="Bege,P  -  M",normalized="bege,p - m")]); current=self.order(items=[self.item(raw="Bege,P - M",normalized="bege,p - m")]); self.assertEqual("already_processed",self.classification(current,[self.historical(old)]).classification)
        self.assertIn("001234",build_order_production_fingerprint(current))

    def test_real_variation_and_sku_changes_are_changed(self):
        variation=self.classification(self.order(items=[self.item(raw="Bege,G",normalized="bege,g")]),[self.historical()]); self.assertEqual("changed",variation.classification)
        sku=self.classification(self.order(items=[self.item(sku="SKU-B")]),[self.historical()]); self.assertEqual("changed",sku.classification)

    def test_latest_historical_occurrence_is_reference(self):
        old=self.historical(self.order(items=[self.item(quantity=1)]),"OLD",datetime(2026,8,1,tzinfo=timezone.utc)); recent=self.historical(self.order(items=[self.item(quantity=2)]),"RECENT",datetime(2026,9,1,tzinfo=timezone.utc)); result=self.classification(self.order(items=[self.item(quantity=1)]),[old,recent]); self.assertEqual("changed",result.classification); self.assertEqual("RECENT",result.previous_batch_number)

    def test_empty_history_all_new_and_counts_active_set(self):
        orders=[self.order(str(i)) for i in range(10)]; analysis=analyze_imported_orders_against_history(orders,[]); self.assertEqual((10,10,0,0),(analysis.total_orders,len(analysis.new_orders),len(analysis.already_processed_orders),len(analysis.changed_orders))); self.assertEqual(10,len(analysis.selected_orders))

    def test_reprocessing_requires_explicit_confirmation(self):
        analyzed=self.classification(self.order(),[self.historical()])
        with self.assertRaises(ValueError): set_order_selection(analyzed,True)
        set_order_selection(analyzed,True,explicitly_confirmed=True)
        self.assertTrue(analyzed.selected_for_current_batch); self.assertTrue(analyzed.manually_included_again)


if __name__=="__main__": unittest.main()

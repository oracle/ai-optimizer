"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# spell-checker: disable
# pylint: disable=import-error
# from time import sleep
# from conftest import COMMON_VARS

#############################################################################
# Test Streamlit UI
#############################################################################
# class TestStreamlit:
#     """Test the Streamlit UI"""

# def test_model_delete_all(app_test):
#     """Deleting Models"""

#     def delete_models(model_config, prefix):
#         "Deletion Logic should be same for any type model"
#         for model_name in model_config.keys():
#             at.button(key=f"{prefix}_{model_name}_edit").click().run()
#             assert at.text_input(key="edit_model_name").value == model_name
#             at.button(key="delete_model").click().run()
#             assert at.success[0].value == f"Model deleted: {model_name}"
#             print(f"=======Models Configured: {len(model_config)}")
#         assert len(model_config) == 0

#     at = app_test("client/content/config/models.py").run()
#     delete_models(at.session_state.ll_model_config, "ll")
#     delete_models(at.session_state.embed_model_config, "embed")


# def test_model_add(app_test):
#     """Adding Models"""
#     at = app_test("client/content/config/models.py").run()
#     at.button(key="add_ll_model").click().run()


# def test_model_update_enabled(app_test):
#     """Editing Models"""
#     at = app_test("client/content/config/models.py").run()


# def test_model_update_url(app_test):
#     """Editing Models"""
#     at = app_test("client/content/config/models.py").run()


# def test_model_delete(app_test):
#     """Deleting Models"""
#     at = app_test("client/content/config/models.py").run()

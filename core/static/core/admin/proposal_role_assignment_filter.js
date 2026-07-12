(function () {
  "use strict";

  function bindProposalRoleAssignmentFilter($) {
    if (typeof $ !== "function") {
      return;
    }

    function proposerField() {
      return $("#id_proposer_member");
    }

    function roleIdentityField() {
      return $("#id_proposer_role_assignment");
    }

    function notifyChanged(roleIdentity) {
      roleIdentity.trigger("change");
      if (roleIdentity[0]) {
        roleIdentity[0].dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function emptyRoleIdentity(roleIdentity) {
      roleIdentity.empty();
      roleIdentity.append(new Option("---------", ""));
      roleIdentity.val("");
      notifyChanged(roleIdentity);
    }

    function reloadRoleIdentity() {
      var proposer = proposerField();
      var roleIdentity = roleIdentityField();

      if (!proposer.length || !roleIdentity.length) {
        return;
      }

      var memberPk = proposer.val();
      var endpoint = roleIdentity.attr("data-role-assignment-options-url") || "/admin/core/proposal/role-assignment-options/";

      emptyRoleIdentity(roleIdentity);
      if (!memberPk || !endpoint) {
        return;
      }

      $.getJSON(endpoint, { member_pk: memberPk }).done(function (data) {
        $.each(data.results || [], function (_index, item) {
          roleIdentity.append(new Option(item.text, item.id));
        });
        notifyChanged(roleIdentity);
      });
    }

    $(document).on("change select2:select", "#id_proposer_member", function () {
      window.setTimeout(reloadRoleIdentity, 0);
    });
  }

  function boot() {
    var adminJQuery = window.django && typeof django.jQuery === "function" ? django.jQuery : null;
    if (adminJQuery) {
      adminJQuery(function () {
        bindProposalRoleAssignmentFilter(adminJQuery);
      });
      return;
    }

    var globalJQuery = typeof window.jQuery === "function" ? window.jQuery : null;
    if (globalJQuery) {
      globalJQuery(function () {
        bindProposalRoleAssignmentFilter(globalJQuery);
      });
      return;
    }
    window.setTimeout(boot, 50);
  }

  boot();
})();

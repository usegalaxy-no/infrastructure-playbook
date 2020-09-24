<template>
    <div class="container">
        <div class="row justify-content-md-center">
            <div class="col col-lg-6">
                <b-alert :show="messageShow" :variant="messageVariant" v-html="messageText" />
                <b-form id="login" @submit.prevent="submitGalaxyLogin()">
                    <b-card no-body header="Welcome to Galaxy, please log in">
                        <b-card-body>
                            <div v-if="enable_oidc">
                                <!-- OIDC login-->
                                <hr class="my-4" />

                                <div v-for="(idp_info, idp) in filtered_oidc_idps" :key="idp" class="m-1">
                                    <span v-if="idp_info['icon']">
                                        <b-button variant="link" class="d-block mt-3" @click="submitOIDCLogin(idp)">
                                            <img :src="idp_info['icon']" height="45" :alt="idp" />
                                        </b-button>
                                    </span>
                                    <span v-else>
                                        <b-button class="d-block mt-3" @click="submitOIDCLogin(idp)">
                                            <i :class="oidc_idps[idp]" />
                                            <img src="/static/images/NeLS-logo.png"> sign in
                                        </b-button>
                                    </span>
                                </div>
                            </div>
                        </b-card-body>
                        <b-card-footer>
                            Don't have an account?
                            <span v-if="allowUserCreation">
                                <a
                                    id="register-toggle"
                                    href="javascript:void(0)"
                                    role="button"
                                    @click.prevent="toggleLogin"
                                    >Register here.</a
                                >
                            </span>
                            <span v-else>
                                Please contact an administrator for assistance.
                            </span>
                        </b-card-footer>
                    </b-card>
                </b-form>

                <b-modal centered id="duplicateEmail" ref="duplicateEmail" title="Duplicate Email" ok-only>
                    <p>
                        There already exists a user with this email. To associate this external login, you must first be
                        logged in as that existing account.
                    </p>

                    <p>
                        Reminder: Registration and usage of multiple accounts is tracked and such accounts are subject
                        to termination and data deletion. Connect existing account now to avoid possible loss of data.
                    </p>
                    -->
                </b-modal>
            </div>

            <div v-if="show_welcome_with_login" class="col">
                <b-embed type="iframe" :src="welcome_url" aspect="1by1" />
            </div>
        </div>
    </div>
</template>

<script>
import axios from "axios";
import Vue from "vue";
import Multiselect from "vue-multiselect";
import BootstrapVue from "bootstrap-vue";
import { getGalaxyInstance } from "app";
import { getAppRoot } from "onload";

Vue.use(BootstrapVue);

export default {
    components: {
        Multiselect,
    },
    props: {
        show_welcome_with_login: {
            type: Boolean,
            required: false,
        },
        welcome_url: {
            type: String,
            required: false,
        },
    },
    data() {
        const galaxy = getGalaxyInstance();
        return {
            login: null,
            password: null,
            url: null,
            provider: null,
            messageText: null,
            messageVariant: null,
            allowUserCreation: galaxy.config.allow_user_creation,
            redirect: galaxy.params.redirect,
            session_csrf_token: galaxy.session_csrf_token,
            enable_oidc: galaxy.config.enable_oidc,
            oidc_idps: galaxy.config.oidc,
            cilogon_idps: [],
            selected: null,
        };
    },
    computed: {
        filtered_oidc_idps() {
            const filtered = Object.assign({}, this.oidc_idps);
            delete filtered.custos;
            delete filtered.cilogon;
            return filtered;
        },
        cilogonListShow() {
            return (
                Object.prototype.hasOwnProperty.call(this.oidc_idps, "cilogon") ||
                Object.prototype.hasOwnProperty.call(this.oidc_idps, "custos")
            );
        },
        messageShow() {
            return this.messageText != null;
        },
    },
    methods: {
        toggleLogin: function () {
            if (this.$root.toggleLogin) {
                this.$root.toggleLogin();
            }
        },
        submitGalaxyLogin: function (method) {
            const rootUrl = getAppRoot();
            axios
                .post(`${rootUrl}user/login`, this.$data)
                .then((response) => {
                    if (response.data.message && response.data.status) {
                        alert(response.data.message);
                    }
                    if (response.data.expired_user) {
                        window.location = `${rootUrl}root/login?expired_user=${response.data.expired_user}`;
                    } else if (response.data.redirect) {
                        window.location = encodeURI(response.data.redirect);
                    } else {
                        window.location = `${rootUrl}`;
                    }
                })
                .catch((error) => {
                    this.messageVariant = "danger";
                    const message = error.response.data && error.response.data.err_msg;
                    this.messageText = message || "Login failed for an unknown reason.";
                });
        },
        submitOIDCLogin: function (idp) {
            const rootUrl = getAppRoot();
            axios
                .post(`${rootUrl}authnz/${idp}/login`)
                .then((response) => {
                    if (response.data.redirect_uri) {
                        window.location = response.data.redirect_uri;
                    }
                })
                .catch((error) => {
                    this.messageVariant = "danger";
                    const message = error.response.data && error.response.data.err_msg;
                    this.messageText = message || "Login failed for an unknown reason.";
                });
        },
        submitCILogon(idp) {
            const rootUrl = getAppRoot();

            axios
                .post(`${rootUrl}authnz/${idp}/login/?idphint=${this.selected.EntityID}`)
                .then((response) => {
                    if (response.data.redirect_uri) {
                        window.location = response.data.redirect_uri;
                    }
                })
                .catch((error) => {
                    this.messageVariant = "danger";
                    const message = error.response.data && error.response.data.err_msg;

                    this.messageText = message || "Login failed for an unknown reason.";
                })
                .finally(() => {
                    var urlParams = new URLSearchParams(window.location.search);

                    if (urlParams.has("message") && urlParams.get("message") == "Duplicate Email") {
                        this.$refs.duplicateEmail.show();
                    }
                });
        },
        reset: function (ev) {
            const rootUrl = getAppRoot();
            ev.preventDefault();
            axios
                .post(`${rootUrl}user/reset_password`, { email: this.login })
                .then((response) => {
                    this.messageVariant = "info";
                    this.messageText = response.data.message;
                })
                .catch((error) => {
                    this.messageVariant = "danger";
                    const message = error.response.data && error.response.data.err_msg;
                    this.messageText = message || "Password reset failed for an unknown reason.";
                });
        },
        getCILogonIdps() {
            const rootUrl = getAppRoot();

            axios.get(`${rootUrl}authnz/get_cilogon_idps`).then((response) => {
                this.cilogon_idps = response.data;
                //List is originally sorted by OrganizationName which can be different from DisplayName
                this.cilogon_idps.sort((a, b) => (a.DisplayName > b.DisplayName ? 1 : -1));
            });
        },
    },
    created() {
        this.getCILogonIdps();
    },
};
</script>
<style scoped>
.card-body {
    overflow: visible;
}
</style>
